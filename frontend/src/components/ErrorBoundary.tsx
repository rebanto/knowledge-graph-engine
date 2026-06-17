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
        <div className="flex h-full flex-col items-center justify-center gap-4 p-12 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-rose-500/10">
            <AlertTriangle size={22} className="text-rose-400" />
          </div>
          <div>
            <p className="text-[14px] font-medium text-zinc-200">Something went wrong</p>
            <p className="mt-1 text-[12.5px] text-zinc-500">
              {this.state.error.message || "An unexpected error occurred in this panel."}
            </p>
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-700 px-3 py-1.5 text-[12.5px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
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
