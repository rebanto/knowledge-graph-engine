type Variant = "default" | "raised" | "flat";

const VARIANT: Record<Variant, string> = {
  // Lit panel - faint top highlight + gradient (see index.css .surface).
  default: "surface",
  // More elevated panel for primary content blocks.
  raised: "surface-raised",
  // Quiet inline card for list items and nested content.
  flat: "border border-ink-700 bg-ink-800/40",
};

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: Variant;
  as?: "div" | "section";
}

// The one card shape. All panels share rounded-xl so corners read consistently;
// callers add their own padding so dense and roomy cards can coexist.
export function Card({ variant = "default", as = "div", className = "", children, ...rest }: CardProps) {
  const Tag = as;
  return (
    <Tag className={`rounded-xl ${VARIANT[variant]} ${className}`} {...rest}>
      {children}
    </Tag>
  );
}
