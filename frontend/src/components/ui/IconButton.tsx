import { forwardRef } from "react";

type Size = "sm" | "md";
type Tone = "default" | "danger" | "brass";

const SIZE: Record<Size, string> = {
  sm: "h-7 w-7 rounded-md",
  md: "h-8 w-8 rounded-lg",
};

const TONE: Record<Tone, string> = {
  default: "text-faint hover:bg-ink-750 hover:text-paper-dim",
  danger: "text-faint hover:bg-ink-750 hover:text-flag",
  brass: "text-muted hover:bg-ink-750 hover:text-brass",
};

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: Size;
  tone?: Tone;
}

// Square, icon-only action - close, refresh, delete, expand, etc. Keeps every
// such control identically sized and spaced across the app.
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { size = "md", tone = "default", className = "", children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={`inline-flex flex-shrink-0 items-center justify-center transition-colors duration-200 disabled:opacity-40 ${SIZE[size]} ${TONE[tone]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
});
