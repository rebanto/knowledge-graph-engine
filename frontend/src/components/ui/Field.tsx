import { forwardRef } from "react";

const BASE =
  "w-full rounded-lg border border-ink-700 bg-ink-900 text-paper outline-none transition-colors duration-200 placeholder:text-faint focus:border-brass/50 disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...rest }, ref) {
    return <input ref={ref} className={`${BASE} px-3 py-2 text-[13px] ${className}`} {...rest} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className = "", ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={`${BASE} resize-none px-3 py-2 text-[13px] leading-relaxed ${className}`}
        {...rest}
      />
    );
  },
);
