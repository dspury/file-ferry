/**
 * Inline icon set.
 *
 * Hand-drawn rather than pulled from a library: the renderer deliberately
 * carries no new dependency surface (plan §7a), and the CSP allows no
 * remote fonts or images, so an icon font or sprite URL is not an option.
 *
 * Every icon inherits `currentColor` and is `aria-hidden` — icons here are
 * always paired with a visible text label, so announcing them again would
 * only duplicate it.
 */
import type { JSX, SVGProps } from 'react';

type IconProps = { size?: number } & Omit<SVGProps<SVGSVGElement>, 'width' | 'height'>;

function Icon({ size = 16, children, ...rest }: IconProps): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function IconDashboard(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </Icon>
  );
}

export function IconActivity(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <path d="M3 12h4l2.5-7 5 14L17 12h4" />
    </Icon>
  );
}

export function IconOffload(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <path d="M12 3v10" />
      <path d="m8 9 4 4 4-4" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </Icon>
  );
}

export function IconOrganize(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <path d="M6.5 13v5.5a1.5 1.5 0 0 0 1.5 1.5h2" />
      <path d="M6.5 13.5v0" />
      <path d="M14 6.5h6" />
      <path d="M14 20h6" />
      <path d="M14 13.5h6" />
    </Icon>
  );
}

export function IconProjects(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <path d="M3 7a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.4.6L11.4 7H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Icon>
  );
}

export function IconMedia(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M3 15h18M8 4v16M16 4v16" />
    </Icon>
  );
}

export function IconEnvironment(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <path d="M12 3 4 6v5.5c0 4.4 3.2 8.2 8 9.5 4.8-1.3 8-5.1 8-9.5V6z" />
      <path d="m9 12 2 2 4-4" />
    </Icon>
  );
}

export function IconSettings(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" />
    </Icon>
  );
}

/** Ferry mark: a hull with a stacked cargo box, drawn filled for the rail. */
export function IconFerry(props: IconProps): JSX.Element {
  return (
    <Icon strokeWidth={1.8} {...props}>
      <path d="M3 15.5h18l-2.5 4a2 2 0 0 1-1.7 1H7.2a2 2 0 0 1-1.7-1z" />
      <path d="M6 15.5V10h12v5.5" />
      <path d="M9.5 10V6.5h5V10" />
    </Icon>
  );
}

export function IconAlert(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5M12 16.2v.1" />
    </Icon>
  );
}

export function IconCheck(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.2 2.4 2.4 4.6-5" />
    </Icon>
  );
}

export function IconInfo(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.8v.1" />
    </Icon>
  );
}

export function IconInbox(props: IconProps): JSX.Element {
  return (
    <Icon size={28} strokeWidth={1.3} {...props}>
      <path d="M3 13h5l1.5 3h5L16 13h5" />
      <path d="M5.4 5.6 3 13v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5l-2.4-7.4A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.9 1.6z" />
    </Icon>
  );
}

export function IconFolderOpen(props: IconProps): JSX.Element {
  return (
    <Icon {...props}>
      <path d="M3 7a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.4.6L11.4 7H19a2 2 0 0 1 2 2v1H3z" />
      <path d="M3 10h18l-1.8 8.4a2 2 0 0 1-2 1.6H6.8a2 2 0 0 1-2-1.6z" />
    </Icon>
  );
}
