import { forwardRef } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  // The single brass call-to-action.
  primary: "bg-brass text-ink-900 enabled:hover:bg-brass-bright",
  // Neutral filled action.
  secondary:
    "border border-ink-600 bg-ink-800 text-paper-dim enabled:hover:border-ink-500 enabled:hover:text-paper",
  // Quiet bordered action that warms to brass on hover (e.g. "New thread").
  outline:
    "border border-ink-700 text-faint enabled:hover:border-brass/40 enabled:hover:text-brass",
  // Borderless, for toolbars and inline actions.
  ghost: "text-muted enabled:hover:bg-ink-750 enabled:hover:text-paper-dim",
  // Destructive.
  danger: "bg-flag text-ink-950 enabled:hover:brightness-110",
};

const SIZE: Record<Size, string> = {
  sm: "gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px]",
  md: "gap-2 rounded-lg px-3.5 py-2 text-[13px]",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, className = "", disabled, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-medium transition-colors duration-200 disabled:opacity-40 ${SIZE[size]} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {loading && <Loader2 size={size === "sm" ? 12 : 13} className="animate-spin" />}
      {children}
    </button>
  );
});
