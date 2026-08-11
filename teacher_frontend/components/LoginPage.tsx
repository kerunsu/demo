import { useState } from 'react';
import { Lock, User, AlertCircle, Mail, Phone, UserCircle, CheckCircle2 } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';

interface LoginPageProps {
  onLogin: (teacher: any) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showErrorDialog, setShowErrorDialog] = useState(false);
  
  // 注册相关状态
  const [showRegisterDialog, setShowRegisterDialog] = useState(false);
  const [registerData, setRegisterData] = useState({
    username: '',
    password: '',
    confirmPassword: '',
    real_name: '',
    email: '',
    phone: '',
  });
  const [isRegistering, setIsRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerSuccess, setRegisterSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!username || !password) {
      setError('请输入用户名和密码');
      setShowErrorDialog(true);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/teacher/login', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          password,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        // 登录成功
        console.log('登录成功:', data.teacher);
        onLogin(data.teacher);
      } else {
        // 登录失败
        setError(data.error || '登录失败，请重试');
        setShowErrorDialog(true);
      }
    } catch (err) {
      console.error('登录请求失败:', err);
      setError('网络错误，请检查服务器连接');
      setShowErrorDialog(true);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-600 rounded-full mb-4">
            <User className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-gray-900 mb-2">教师端登录</h1>
          <p className="text-gray-600">欢迎回来，请登录您的账号</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label htmlFor="username" className="block text-gray-700 mb-2">
              用户名
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="请输入用户名"
                required
              />
            </div>
          </div>

          <div>
            <label htmlFor="password" className="block text-gray-700 mb-2">
              密码
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="请输入密码"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 disabled:cursor-not-allowed text-white py-3 rounded-lg transition-colors flex items-center justify-center"
          >
            {isLoading ? (
              <>
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                登录中...
              </>
            ) : (
              '登录'
            )}
          </button>
        </form>

        <div className="mt-6 flex justify-between items-center">
          <button
            type="button"
            onClick={() => setShowRegisterDialog(true)}
            className="text-indigo-600 hover:text-indigo-700 transition-colors"
          >
            注册
          </button>
          <a href="#" className="text-indigo-600 hover:text-indigo-700 transition-colors">
            忘记密码?
          </a>
        </div>
      </div>

      {/* 错误提示弹窗 */}
      <AlertDialog open={showErrorDialog} onOpenChange={setShowErrorDialog}>
        <AlertDialogContent className="sm:max-w-md">
          <AlertDialogHeader>
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <AlertCircle className="w-5 h-5 text-red-600" />
              </div>
              <div>
                <AlertDialogTitle className="text-left">登录失败</AlertDialogTitle>
                <AlertDialogDescription className="text-left mt-1">
                  {error || '登录过程中发生错误，请重试'}
                </AlertDialogDescription>
              </div>
            </div>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction
              onClick={() => {
                setShowErrorDialog(false);
                setError(null);
              }}
              className="bg-indigo-600 hover:bg-indigo-700"
            >
              确定
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 注册对话框 */}
      <Dialog open={showRegisterDialog} onOpenChange={setShowRegisterDialog}>
        <DialogContent className="sm:max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold text-gray-900">教师注册</DialogTitle>
            <DialogDescription className="text-gray-600">
              请填写以下信息完成注册
            </DialogDescription>
          </DialogHeader>

          {registerSuccess ? (
            <div className="py-6">
              <div className="flex flex-col items-center justify-center gap-4">
                <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
                  <CheckCircle2 className="w-8 h-8 text-green-600" />
                </div>
                <div className="text-center">
                  <h3 className="text-lg font-semibold text-gray-900 mb-2">注册成功！</h3>
                  <p className="text-gray-600">您的账户已创建，现在可以登录了</p>
                </div>
                <button
                  onClick={() => {
                    setShowRegisterDialog(false);
                    setRegisterSuccess(false);
                    setRegisterData({
                      username: '',
                      password: '',
                      confirmPassword: '',
                      real_name: '',
                      email: '',
                      phone: '',
                    });
                  }}
                  className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2 px-4 rounded-lg transition-colors"
                >
                  确定
                </button>
              </div>
            </div>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                
                // 验证必填字段
                if (!registerData.username || !registerData.password) {
                  setRegisterError('用户名和密码不能为空');
                  return;
                }

                // 验证密码确认
                if (registerData.password !== registerData.confirmPassword) {
                  setRegisterError('两次输入的密码不一致');
                  return;
                }

                // 验证密码长度
                if (registerData.password.length < 6) {
                  setRegisterError('密码长度至少为6位');
                  return;
                }

                setIsRegistering(true);
                setRegisterError(null);

                try {
                  const response = await fetch('/api/teacher/register', {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                      username: registerData.username,
                      password: registerData.password,
                      real_name: registerData.real_name || null,
                      email: registerData.email || null,
                      phone: registerData.phone || null,
                    }),
                  });

                  const data = await response.json();

                  if (response.ok && data.success) {
                    // 注册成功
                    setRegisterSuccess(true);
                    console.log('注册成功:', data.teacher);
                  } else {
                    // 注册失败
                    setRegisterError(data.error || '注册失败，请重试');
                  }
                } catch (err) {
                  console.error('注册请求失败:', err);
                  setRegisterError('网络错误，请检查服务器连接');
                } finally {
                  setIsRegistering(false);
                }
              }}
              className="space-y-4"
            >
              {/* 用户名 */}
              <div>
                <label htmlFor="register-username" className="block text-gray-700 mb-2 text-sm">
                  用户名 <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-username"
                    type="text"
                    value={registerData.username}
                    onChange={(e) => setRegisterData({ ...registerData, username: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请输入用户名"
                    required
                  />
                </div>
              </div>

              {/* 密码 */}
              <div>
                <label htmlFor="register-password" className="block text-gray-700 mb-2 text-sm">
                  密码 <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-password"
                    type="password"
                    value={registerData.password}
                    onChange={(e) => setRegisterData({ ...registerData, password: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请输入密码（至少6位）"
                    required
                    minLength={6}
                  />
                </div>
              </div>

              {/* 确认密码 */}
              <div>
                <label htmlFor="register-confirm-password" className="block text-gray-700 mb-2 text-sm">
                  确认密码 <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-confirm-password"
                    type="password"
                    value={registerData.confirmPassword}
                    onChange={(e) => setRegisterData({ ...registerData, confirmPassword: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请再次输入密码"
                    required
                  />
                </div>
              </div>

              {/* 真实姓名 */}
              <div>
                <label htmlFor="register-real-name" className="block text-gray-700 mb-2 text-sm">
                  真实姓名
                </label>
                <div className="relative">
                  <UserCircle className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-real-name"
                    type="text"
                    value={registerData.real_name}
                    onChange={(e) => setRegisterData({ ...registerData, real_name: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请输入真实姓名（可选）"
                  />
                </div>
              </div>

              {/* 邮箱 */}
              <div>
                <label htmlFor="register-email" className="block text-gray-700 mb-2 text-sm">
                  邮箱
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-email"
                    type="email"
                    value={registerData.email}
                    onChange={(e) => setRegisterData({ ...registerData, email: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请输入邮箱（可选）"
                  />
                </div>
              </div>

              {/* 手机号 */}
              <div>
                <label htmlFor="register-phone" className="block text-gray-700 mb-2 text-sm">
                  手机号
                </label>
                <div className="relative">
                  <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="register-phone"
                    type="tel"
                    value={registerData.phone}
                    onChange={(e) => setRegisterData({ ...registerData, phone: e.target.value })}
                    className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    placeholder="请输入手机号（可选）"
                  />
                </div>
              </div>

              {/* 错误提示 */}
              {registerError && (
                <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
                  <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
                  <p className="text-sm text-red-600">{registerError}</p>
                </div>
              )}

              <DialogFooter className="gap-2 sm:gap-0">
                <button
                  type="button"
                  onClick={() => {
                    setShowRegisterDialog(false);
                    setRegisterError(null);
                    setRegisterData({
                      username: '',
                      password: '',
                      confirmPassword: '',
                      real_name: '',
                      email: '',
                      phone: '',
                    });
                  }}
                  className="px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                  disabled={isRegistering}
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={isRegistering}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center"
                >
                  {isRegistering ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      注册中...
                    </>
                  ) : (
                    '注册'
                  )}
                </button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
