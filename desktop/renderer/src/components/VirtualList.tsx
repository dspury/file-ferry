/**
 * Virtualized list for large asset / project / job inventories.
 *
 * Renders only the rows in the viewport plus a small overscan, so a
 * library of thousands of assets stays responsive (plan §8.2 "virtualized
 * lists for large asset inventories", §10 Pkg7 step 4 "large-library
 * rendering behavior"). Pure row-window math is in lib/virtualize.ts.
 */
import { useEffect, useRef, useState, type JSX } from 'react';
import type { ReactNode } from 'react';
import { windowForScroll } from '../lib/virtualize.js';

export interface VirtualListProps<T> {
  readonly items: readonly T[];
  readonly rowHeight: number;
  readonly height: number;
  readonly overscan?: number;
  readonly renderRow: (item: T, index: number) => ReactNode;
  readonly ariaLabel?: string;
}

export function VirtualList<T>({
  items,
  rowHeight,
  height,
  overscan = 5,
  renderRow,
  ariaLabel = 'List',
}: VirtualListProps<T>): JSX.Element {
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const { start, end, totalHeight } = windowForScroll(
    scrollTop,
    height,
    rowHeight,
    items.length,
    overscan,
  );

  const visible = items.slice(start, end);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => setScrollTop(el.scrollTop);
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div
      ref={containerRef}
      role="list"
      aria-label={ariaLabel}
      style={{ height, overflowY: 'auto', position: 'relative' }}
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        {visible.map((item, i) => {
          const index = start + i;
          return (
            <div
              key={index}
              role="listitem"
              style={{
                position: 'absolute',
                top: index * rowHeight,
                left: 0,
                right: 0,
                height: rowHeight,
              }}
            >
              {renderRow(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
