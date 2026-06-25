import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="dot-grid flex h-full flex-col items-center justify-center gap-4 p-12 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-flag-dim">
            <AlertTriangle size={22} className="text-flag" />
          </div>
          <div>
            <p className="font-display text-[17px] font-medium text-paper">This panel came loose</p>
            <p className="mt-1 text-[12.5px] text-muted">
              {this.state.error.message || "Something unexpected happened in here."}
            </p>
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-[12.5px] text-muted transition-colors hover:border-brass/40 hover:text-paper-dim"
          >
            <RefreshCw size={12} />
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
