name: Bug report
description: Something in ferry does not do what it should
body:
  - type: markdown
    attributes:
      value: |
        Please do not use this template for security issues — report those
        privately to security@dspury.com instead. See `SECURITY.md`.

  - type: textarea
    id: what-happened
    attributes:
      label: What happened
      description: What you did, what you expected, and what happened instead.
    validations:
      required: true

  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      placeholder: |
        1.
        2.
        3.
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: ferry version
      description: '`ferry --version`, or `app.diagnostics` for the packaged app.'
    validations:
      required: true

  - type: dropdown
    id: install
    attributes:
      label: How did you install it?
      options:
        - From source (clone + pip install)
        - Packaged macOS app
        - Other
    validations:
      required: true

  - type: input
    id: os
    attributes:
      label: OS and version
    validations:
      required: true

  - type: input
    id: python
    attributes:
      label: Python version
    validations:
      required: false

  - type: input
    id: ffmpeg
    attributes:
      label: FFmpeg version
      description: 'First line of `ffmpeg -version`.'
    validations:
      required: false

  - type: textarea
    id: sample-data
    attributes:
      label: Does it reproduce with the sample data?
      description: '`bash examples/run-demo.sh` — yes/no, and what happens.'
    validations:
      required: false

  - type: textarea
    id: receipt
    attributes:
      label: Receipt or audit entry
      description: |
        If the run produced one, this is the fastest route to a real diagnosis.
        `docs/RELEASE.md` documents where receipts and the audit database live.
        Please redact any real media paths you would rather not publish.
    validations:
      required: false

  - type: textarea
    id: logs
    attributes:
      label: Logs, error text, or screenshots
      description: |
        Full error output is much more useful than a summary. Please check it
        for paths or names you would rather not post publicly.
    validations:
      required: false
