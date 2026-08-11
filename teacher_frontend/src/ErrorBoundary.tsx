import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('教师端发生未捕获错误:', error, info.componentStack);
  }

  private resetNavigation = () => {
    try {
      localStorage.removeItem('teacherAppNav');
    } catch (error) {
      console.warn('无法清理教师端导航状态:', error);
    }
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-xl">
          <h1 className="text-xl font-semibold text-slate-900">教师端暂时无法显示</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            页面状态或服务数据出现异常。可以先重试；若问题持续，请返回安全页面后重新进入课程。
          </p>
          <details className="mt-4 rounded-lg bg-slate-50 p-3 text-left text-xs text-slate-500">
            <summary className="cursor-pointer font-medium">错误详情</summary>
            <pre className="mt-2 overflow-auto whitespace-pre-wrap break-words">
              {this.state.error.message || String(this.state.error)}
            </pre>
          </details>
          <div className="mt-6 flex justify-center gap-3">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              重新加载
            </button>
            <button
              type="button"
              onClick={this.resetNavigation}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              返回安全页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
