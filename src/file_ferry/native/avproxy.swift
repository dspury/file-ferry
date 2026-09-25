// ferry-avproxy — a ProRes proxy through AVFoundation, on the media engine.
//
// ffmpeg's VideoToolbox hwaccel refuses H.264 High 4:2:2 10-bit ("Error
// submitting packet to decoder") — the Sony XAVC S 4:2:2 that FX3, FX6 and
// a7S III cameras record — so ffmpeg decodes it in software, ~200 CPU-seconds
// per 95 s of 4K. AVFoundation hands the same stream to the hardware decoder
// (measured on an M4 Pro: 261 fps, 0.6 s of CPU), scales it there, and
// encodes ProRes on the ProRes engine.
//
// Usage: ferry-avproxy --in SRC --out DST.mov --height 720 --codec proxy
//                      [--timecode HH:MM:SS:FF]
//   codec: proxy | lt | 422 | hq | 4444
// Copies the source timecode track when there is one (samples passed
// through). Sony XAVC MP4s have none — their start timecode lives in the
// `rtmd` real-time-metadata stream, which ffprobe reads and AVFoundation does
// not — so the caller passes it with --timecode and a standard QuickTime
// timecode track is written from it. Writes every
// audio track as interleaved PCM at its source rate and channel count, keeps
// the source's colour tags. Prints one JSON line on success; exits non-zero
// with a message on stderr otherwise.

import AVFoundation
import CoreMedia
import Foundation

struct Failure: Error { let message: String }

func arg(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

func codecType(_ name: String) throws -> AVVideoCodecType {
    switch name.lowercased() {
    case "proxy": return .proRes422Proxy
    case "lt": return .proRes422LT
    case "422": return .proRes422
    case "hq": return .proRes422HQ
    case "4444": return .proRes4444
    default: throw Failure(message: "unsupported codec '\(name)' (proxy|lt|422|hq|4444)")
    }
}

func even(_ v: Double) -> Int { max(2, Int((v / 2).rounded()) * 2) }

/// A timecode label as a frame number on its nominal rate; drop-frame aware.
func frameNumber(_ label: String, quanta: Int, dropFrame: Bool) throws -> Int32 {
    let parts = label.split(whereSeparator: { ":;.".contains($0) }).compactMap { Int($0) }
    guard parts.count == 4 else { throw Failure(message: "unreadable timecode '\(label)'") }
    let (h, m, s, f) = (parts[0], parts[1], parts[2], parts[3])
    var frames = ((h * 60 + m) * 60 + s) * quanta + f
    if dropFrame {
        let dropped = quanta / 15            // 2 at 29.97, 4 at 59.94
        let minutes = h * 60 + m
        frames -= dropped * (minutes - minutes / 10)
    }
    return Int32(frames)
}

/// A one-sample QuickTime timecode track starting at `label`.
func synthesizedTimecode(_ label: String, frameDuration: CMTime, duration: CMTime)
    throws -> (AVAssetWriterInput, CMSampleBuffer)
{
    let quanta = Int((Double(frameDuration.timescale) / Double(frameDuration.value)).rounded())
    let dropFrame = label.contains(";") && (quanta == 30 || quanta == 60) && frameDuration.value == 1001
    var flags = kCMTimeCodeFlag_24HourMax
    if dropFrame { flags |= kCMTimeCodeFlag_DropFrame }
    var desc: CMTimeCodeFormatDescription?
    var status = CMTimeCodeFormatDescriptionCreate(
        allocator: kCFAllocatorDefault, timeCodeFormatType: kCMTimeCodeFormatType_TimeCode32,
        frameDuration: frameDuration, frameQuanta: UInt32(quanta), flags: flags,
        extensions: nil, formatDescriptionOut: &desc)
    guard status == noErr, let desc else { throw Failure(message: "timecode format: \(status)") }

    var value = try frameNumber(label, quanta: quanta, dropFrame: dropFrame).bigEndian
    var block: CMBlockBuffer?
    status = CMBlockBufferCreateWithMemoryBlock(
        allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: 4,
        blockAllocator: kCFAllocatorDefault, customBlockSource: nil, offsetToData: 0,
        dataLength: 4, flags: kCMBlockBufferAssureMemoryNowFlag, blockBufferOut: &block)
    guard status == noErr, let block else { throw Failure(message: "timecode block: \(status)") }
    CMBlockBufferReplaceDataBytes(with: &value, blockBuffer: block, offsetIntoDestination: 0, dataLength: 4)

    var timing = CMSampleTimingInfo(duration: duration, presentationTimeStamp: .zero, decodeTimeStamp: .invalid)
    var size = 4
    var sample: CMSampleBuffer?
    status = CMSampleBufferCreate(
        allocator: kCFAllocatorDefault, dataBuffer: block, dataReady: true,
        makeDataReadyCallback: nil, refcon: nil, formatDescription: desc, sampleCount: 1,
        sampleTimingEntryCount: 1, sampleTimingArray: &timing, sampleSizeEntryCount: 1,
        sampleSizeArray: &size, sampleBufferOut: &sample)
    guard status == noErr, let sample else { throw Failure(message: "timecode sample: \(status)") }
    let input = AVAssetWriterInput(mediaType: .timecode, outputSettings: nil, sourceFormatHint: desc)
    input.expectsMediaDataInRealTime = false
    return (input, sample)
}

/// Pumps one reader output into one writer input on its own queue.
final class Pump {
    let output: AVAssetReaderOutput
    let input: AVAssetWriterInput
    let queue: DispatchQueue
    var samples = 0

    init(_ output: AVAssetReaderOutput, _ input: AVAssetWriterInput, _ label: String) {
        self.output = output
        self.input = input
        self.queue = DispatchQueue(label: "ferry.avproxy.\(label)")
    }

    func start(_ group: DispatchGroup, reader: AVAssetReader, writer: AVAssetWriter) {
        group.enter()
        var done = false
        input.requestMediaDataWhenReady(on: queue) { [self] in
            while input.isReadyForMoreMediaData && !done {
                if writer.status == .failed {
                    done = true
                } else if reader.status == .reading, let sample = output.copyNextSampleBuffer() {
                    if !input.append(sample) { done = true }
                    samples += 1
                } else {
                    done = true
                }
            }
            if done {
                input.markAsFinished()
                group.leave()
            }
        }
    }
}

func run() async throws -> [String: Any] {
    guard let src = arg("--in"), let dst = arg("--out") else {
        throw Failure(message: "usage: ferry-avproxy --in SRC --out DST.mov --height N --codec proxy")
    }
    let height = Int(arg("--height") ?? "1080") ?? 1080
    let codec = try codecType(arg("--codec") ?? "proxy")
    let tenBit = [AVVideoCodecType.proRes422, .proRes422HQ, .proRes4444].contains(codec)

    let asset = AVURLAsset(url: URL(fileURLWithPath: src),
                           options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
    guard let video = try await asset.loadTracks(withMediaType: .video).first else {
        throw Failure(message: "no video track in \(src)")
    }
    let audio = try await asset.loadTracks(withMediaType: .audio)
    let timecode = try await asset.loadTracks(withMediaType: .timecode).first

    let natural = try await video.load(.naturalSize)
    let transform = try await video.load(.preferredTransform)
    let formats = try await video.load(.formatDescriptions)
    let extensions = formats.first.flatMap { CMFormatDescriptionGetExtensions($0) as? [String: Any] } ?? [:]
    let outHeight = min(height, Int(abs(natural.height)))
    let outWidth = even(Double(abs(natural.width)) * Double(outHeight) / Double(abs(natural.height)))

    let reader = try AVAssetReader(asset: asset)
    let url = URL(fileURLWithPath: dst)
    try? FileManager.default.removeItem(at: url)
    let writer = try AVAssetWriter(outputURL: url, fileType: .mov)

    // Decode and scale in VideoToolbox: the reader delivers frames already at
    // the proxy size, in the 4:2:2 layout the ProRes encoder takes directly.
    let pixelFormat = tenBit ? kCVPixelFormatType_422YpCbCr10BiPlanarVideoRange
                             : kCVPixelFormatType_422YpCbCr8
    let videoOut = AVAssetReaderTrackOutput(track: video, outputSettings: [
        kCVPixelBufferPixelFormatTypeKey as String: pixelFormat,
        kCVPixelBufferWidthKey as String: outWidth,
        kCVPixelBufferHeightKey as String: outHeight,
    ])
    videoOut.alwaysCopiesSampleData = false
    reader.add(videoOut)

    var videoSettings: [String: Any] = [
        AVVideoCodecKey: codec,
        AVVideoWidthKey: outWidth,
        AVVideoHeightKey: outHeight,
    ]
    var colour: [String: Any] = [:]
    if let p = extensions[kCMFormatDescriptionExtension_ColorPrimaries as String] { colour[AVVideoColorPrimariesKey] = p }
    if let t = extensions[kCMFormatDescriptionExtension_TransferFunction as String] { colour[AVVideoTransferFunctionKey] = t }
    if let m = extensions[kCMFormatDescriptionExtension_YCbCrMatrix as String] { colour[AVVideoYCbCrMatrixKey] = m }
    if colour.count == 3 { videoSettings[AVVideoColorPropertiesKey] = colour }
    let videoIn = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
    videoIn.expectsMediaDataInRealTime = false
    videoIn.transform = transform
    // The source's own timescale: the writer default rounded 119.88 fps
    // (1001/120000 s frames) to a track that reads as 120 fps.
    videoIn.mediaTimeScale = try await video.load(.naturalTimeScale)
    guard writer.canAdd(videoIn) else { throw Failure(message: "writer refused the video input") }
    writer.add(videoIn)
    var pumps = [Pump(videoOut, videoIn, "video")]

    for (i, track) in audio.enumerated() {
        guard let desc = try await track.load(.formatDescriptions).first,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee else { continue }
        let channels = Int(asbd.mChannelsPerFrame)
        let pcm: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: asbd.mSampleRate,
            AVNumberOfChannelsKey: channels,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let out = AVAssetReaderTrackOutput(track: track, outputSettings: pcm)
        reader.add(out)
        var writerPCM = pcm
        if channels > 2 {
            // Beyond stereo the writer needs an explicit layout; discrete keeps
            // every channel as recorded.
            var layout = AudioChannelLayout()
            layout.mChannelLayoutTag = kAudioChannelLayoutTag_DiscreteInOrder | UInt32(channels)
            writerPCM[AVChannelLayoutKey] = Data(bytes: &layout, count: MemoryLayout<AudioChannelLayout>.size)
        }
        let input = AVAssetWriterInput(mediaType: .audio, outputSettings: writerPCM)
        input.expectsMediaDataInRealTime = false
        guard writer.canAdd(input) else { throw Failure(message: "writer refused audio track \(i)") }
        writer.add(input)
        pumps.append(Pump(out, input, "audio\(i)"))
    }

    var timecodeSource = "none"
    var synthesized: (AVAssetWriterInput, CMSampleBuffer)?
    if timecode == nil, let label = arg("--timecode") {
        let frameDuration = try await video.load(.minFrameDuration)
        let duration = try await asset.load(.duration)
        let made = try synthesizedTimecode(label, frameDuration: frameDuration, duration: duration)
        guard writer.canAdd(made.0) else { throw Failure(message: "writer refused the timecode track") }
        writer.add(made.0)
        if videoIn.canAddTrackAssociation(withTrackOf: made.0, type: AVAssetTrack.AssociationType.timecode.rawValue) {
            videoIn.addTrackAssociation(withTrackOf: made.0, type: AVAssetTrack.AssociationType.timecode.rawValue)
        }
        synthesized = made
        timecodeSource = "argument"
    }
    if let tc = timecode, let desc = try await tc.load(.formatDescriptions).first {
        // Passed through untouched: the proxy starts at the camera's timecode,
        // which is what an offline edit relinks against.
        let out = AVAssetReaderTrackOutput(track: tc, outputSettings: nil)
        let input = AVAssetWriterInput(mediaType: .timecode, outputSettings: nil, sourceFormatHint: desc)
        input.expectsMediaDataInRealTime = false
        if reader.canAdd(out), writer.canAdd(input) {
            reader.add(out)
            writer.add(input)
            if videoIn.canAddTrackAssociation(withTrackOf: input, type: AVAssetTrack.AssociationType.timecode.rawValue) {
                videoIn.addTrackAssociation(withTrackOf: input, type: AVAssetTrack.AssociationType.timecode.rawValue)
            }
            pumps.append(Pump(out, input, "timecode"))
            timecodeSource = "source track"
        }
    }

    guard reader.startReading() else {
        throw Failure(message: "reader: \(reader.error?.localizedDescription ?? "could not start")")
    }
    guard writer.startWriting() else {
        throw Failure(message: "writer: \(writer.error?.localizedDescription ?? "could not start")")
    }
    let start = try await asset.load(.duration)
    writer.startSession(atSourceTime: .zero)
    let started = Date()
    if let (input, sample) = synthesized {
        while !input.isReadyForMoreMediaData { try await Task.sleep(nanoseconds: 1_000_000) }
        guard input.append(sample) else {
            throw Failure(message: "timecode: \(writer.error?.localizedDescription ?? "append failed")")
        }
        input.markAsFinished()
    }
    let group = DispatchGroup()
    pumps.forEach { $0.start(group, reader: reader, writer: writer) }
    await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
        group.notify(queue: .global()) { c.resume() }
    }
    if reader.status == .failed {
        writer.cancelWriting()
        throw Failure(message: "reader: \(reader.error?.localizedDescription ?? "failed")")
    }
    await writer.finishWriting()
    if writer.status != .completed {
        throw Failure(message: "writer: \(writer.error?.localizedDescription ?? "status \(writer.status.rawValue)")")
    }
    return [
        "width": outWidth, "height": outHeight,
        "frames": pumps[0].samples, "audio_tracks": audio.count,
        "timecode": timecodeSource,
        "duration_seconds": CMTimeGetSeconds(start),
        "elapsed_seconds": Date().timeIntervalSince(started),
    ]
}

let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0
Task {
    do {
        let result = try await run()
        let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    } catch let f as Failure {
        FileHandle.standardError.write(Data((f.message + "\n").utf8))
        exitCode = 1
    } catch {
        FileHandle.standardError.write(Data(("\(error)\n").utf8))
        exitCode = 1
    }
    semaphore.signal()
}
semaphore.wait()
exit(exitCode)
