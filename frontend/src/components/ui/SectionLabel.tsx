// The recurring small-caps "field label" motif. Wraps the .eyebrow utility so
// every section heading shares one component (and one default colour).
export function SectionLabel({ className = "", children, ...rest }: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={`eyebrow text-faint ${className}`} {...rest}>
      {children}
    </p>
  );
}
