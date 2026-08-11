import { useState, useEffect } from 'react';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Line,
  LineChart,
  Bar,
  BarChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';
import {
  User,
  UserCircle,
  Baby,
  FileText,
  Activity,
  TrendingUp,
  LogOut,
  ChevronDown,
  Loader2,
  Plus,
  Upload,
  X,
  ExternalLink,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';

interface Teacher {
  id: number;
  username: string;
  real_name: string | null;
  email: string | null;
  phone: string | null;
}

function StudentAvatar({
  src,
  name,
  size = 'md',
}: {
  src?: string | null;
  name: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const [failed, setFailed] = useState(false);
  const sizeClass =
    size === 'lg' ? 'w-16 h-16' : size === 'sm' ? 'w-10 h-10' : 'w-12 h-12';
  const iconClass =
    size === 'lg' ? 'w-8 h-8' : size === 'sm' ? 'w-5 h-5' : 'w-6 h-6';

  if (!src || failed) {
    return (
      <div
        className={`${sizeClass} rounded-full bg-sky-50 flex items-center justify-center shrink-0 border border-sky-100`}
        aria-label={name}
      >
        <Baby className={`${iconClass} text-sky-500`} />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={name}
      className={`${sizeClass} rounded-full object-cover shrink-0`}
      onError={() => setFailed(true)}
    />
  );
}

function AdultAvatar({
  src,
  name,
  size = 'sm',
}: {
  src?: string | null;
  name: string;
  size?: 'sm' | 'md';
}) {
  const [failed, setFailed] = useState(false);
  const sizeClass = size === 'md' ? 'w-12 h-12' : 'w-10 h-10';
  const iconClass = size === 'md' ? 'w-6 h-6' : 'w-5 h-5';

  if (!src || failed) {
    return (
      <div
        className={`${sizeClass} rounded-full bg-indigo-50 flex items-center justify-center shrink-0 border border-indigo-100`}
        aria-label={name}
      >
        <User className={`${iconClass} text-indigo-500`} />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={name}
      className={`${sizeClass} rounded-full object-cover shrink-0`}
      onError={() => setFailed(true)}
    />
  );
}

interface StudentInfoPageProps {
  onStartAssessment: () => void;
  onStartTraining: () => void;
  selectedStudent: string | null;
  onSelectStudent: (id: string) => void;
  onLogout: () => void;
  currentTeacher: Teacher | null;
  preparing?: boolean;
  onViewReport?: (trainingSessionId: string) => void;
}

interface Student {
  id: number;
  name: string;
  avatar: string | null;
  age: number | null;
  preference: string | null;
  teacher: string | null;
  screening: string | null;
  abilities: Array<{ subject: string; score: number }>;
  trainingData: Array<{ date: string; count: number }>;
  has_training?: boolean;
  latest_behavior_session_id?: string | null;
  imitation_placeholder?: boolean;
}

interface TrainingSession {
  id: number;
  date: string;
  start_time: string | null;
  behavior_session_id: string | null;
  overall_score: number | null;
  report_status: string | null;
  training_details: Array<{
    course_type_name: string;
    count: number;
  }>;
}

interface InterventionData {
  behavior_session_id: string;
  analysis?: string | null;
  recommendations: Array<{ title: string; body: string }>;
  report_status?: string | null;
  generated_at?: string | null;
  overall_score?: number | null;
}

const COURSE_SERIES = ['命名', '拟声', '模仿', '配对', '排序'] as const;

const API_BASE_URL = '';

// 能力类型颜色配置
const ABILITY_COLORS = [
  '#4f46e5', // 注意力 - indigo
  '#10b981', // 模仿 - green
  '#f59e0b', // 配对 - amber
  '#ef4444', // 排序 - red
  '#8b5cf6', // 表达性语言 - purple
  '#06b6d4', // 接收性语言 - cyan
];

// 课程类型颜色配置
const COURSE_COLORS = [
  '#4f46e5', // 命名 - indigo
  '#10b981', // 拟声 - green
  '#f59e0b', // 模仿 - amber
  '#ef4444', // 配对 - red
  '#8b5cf6', // 排序 - purple
];

export function StudentInfoPage({
  onStartAssessment,
  onStartTraining,
  selectedStudent,
  onSelectStudent,
  onLogout,
  currentTeacher,
  preparing = false,
  onViewReport,
}: StudentInfoPageProps) {
  const [students, setStudents] = useState<Student[]>([]);
  const [currentStudent, setCurrentStudent] = useState<Student | null>(null);
  const [abilitiesHistory, setAbilitiesHistory] = useState<any[]>([]);
  const [trainingSessions, setTrainingSessions] = useState<TrainingSession[]>([]);
  const [intervention, setIntervention] = useState<InterventionData | null>(null);
  const [infoPanelTab, setInfoPanelTab] = useState<'screening' | 'intervention'>('screening');
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showLogoutMenu, setShowLogoutMenu] = useState(false);
  const [abilityView, setAbilityView] = useState<'radar' | 'trend'>('radar');
  const [hiddenAbilities, setHiddenAbilities] = useState<Set<string>>(new Set());
  const [reportHint, setReportHint] = useState<string | null>(null);
  
  // 添加学生相关状态
  const [showAddStudentDialog, setShowAddStudentDialog] = useState(false);
  const [newStudent, setNewStudent] = useState({
    name: '',
    age: '',
    preference: '',
    teacher: '',
    screening: '',
    avatar: null as string | null,
  });
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [isAddingStudent, setIsAddingStudent] = useState(false);
  const [addStudentError, setAddStudentError] = useState<string | null>(null);

  // 获取学生列表
  const fetchStudents = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/students`);
      const data = await response.json();
      if (data.success) {
        setStudents(data.students);
        // 如果有选中的学生，加载其详情
        if (selectedStudent) {
          loadStudentDetail(parseInt(selectedStudent));
        } else if (data.students.length > 0) {
          // 默认选择第一个学生
          const firstStudentId = data.students[0].id;
          onSelectStudent(firstStudentId.toString());
          loadStudentDetail(firstStudentId);
        }
      }
    } catch (error) {
      console.error('获取学生列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStudents();
  }, []);

  // 当选中学生改变时，加载详情
  useEffect(() => {
    if (selectedStudent) {
      loadStudentDetail(parseInt(selectedStudent));
    }
  }, [selectedStudent]);

  // 加载学生详情
  const loadStudentDetail = async (studentId: number) => {
    try {
      setLoadingDetail(true);
      setReportHint(null);

      // 获取学生基本信息（包含最新能力数据和训练数据统计）
      const detailResponse = await fetch(`${API_BASE_URL}/api/students/${studentId}`);
      const detailData = await detailResponse.json();
      let studentHasTraining = false;
      if (detailData.success) {
        setCurrentStudent(detailData.student);
        studentHasTraining = Boolean(
          detailData.student?.has_training ||
            (detailData.student?.abilities && detailData.student.abilities.length > 0)
        );
      }

      // 获取能力历史记录
      const abilitiesResponse = await fetch(
        `${API_BASE_URL}/api/students/${studentId}/abilities`
      );
      const abilitiesData = await abilitiesResponse.json();
      if (abilitiesData.success) {
        setAbilitiesHistory(abilitiesData.abilities_history);
      }

      // 获取训练记录（按次保留，便于跳转报告）
      const sessionsResponse = await fetch(
        `${API_BASE_URL}/api/students/${studentId}/training-sessions?per_page=30`
      );
      const sessionsData = await sessionsResponse.json();
      if (sessionsData.success) {
        const sessions: TrainingSession[] = (sessionsData.sessions || []).map(
          (session: any) => ({
            id: session.id,
            date: session.date ? String(session.date).split('T')[0] : '',
            start_time: session.start_time || null,
            behavior_session_id: session.behavior_session_id || null,
            overall_score:
              session.overall_score === null || session.overall_score === undefined
                ? null
                : Number(session.overall_score),
            report_status: session.report_status || null,
            training_details: (session.training_details || []).map((detail: any) => ({
              course_type_name: detail.course_type_name,
              count: detail.count || 0,
            })),
          })
        );
        // 柱图按时间升序（旧 → 新）
        sessions.sort((a, b) => {
          const keyA = `${a.date} ${a.start_time || ''}`;
          const keyB = `${b.date} ${b.start_time || ''}`;
          return keyA.localeCompare(keyB);
        });
        setTrainingSessions(sessions);
        if (sessions.length > 0) {
          studentHasTraining = true;
        }
      }

      // 最新干预建议
      const interventionResponse = await fetch(
        `${API_BASE_URL}/api/students/${studentId}/latest-intervention`
      );
      const interventionData = await interventionResponse.json();
      if (interventionData.success && interventionData.data) {
        setIntervention({
          behavior_session_id: interventionData.data.behavior_session_id,
          analysis: interventionData.data.analysis,
          recommendations: interventionData.data.recommendations || [],
          report_status: interventionData.data.report_status,
          generated_at: interventionData.data.generated_at,
          overall_score: interventionData.data.overall_score,
        });
      } else {
        setIntervention(null);
      }

      // 有训练记录则默认展示干预建议 Tab
      setInfoPanelTab(studentHasTraining ? 'intervention' : 'screening');
    } catch (error) {
      console.error('获取学生详情失败:', error);
    } finally {
      setLoadingDetail(false);
    }
  };

  const openReport = async (behaviorSessionId: string | null | undefined) => {
    if (!behaviorSessionId) {
      setReportHint('该记录无关联评估报告');
      return;
    }
    if (!onViewReport) {
      setReportHint('暂无法打开该次报告，请稍后重试');
      return;
    }
    try {
      const statusRes = await fetch(
        `${API_BASE_URL}/api/report/${behaviorSessionId}/review-status`
      );
      const statusJson = await statusRes.json();
      if (
        !statusJson?.success ||
        statusJson.data?.publicationStatus !== 'published'
      ) {
        setReportHint('报告审核中，尚未推送至教师端');
        return;
      }
    } catch {
      setReportHint('暂无法确认报告状态，请稍后重试');
      return;
    }
    setReportHint(null);
    onViewReport(behaviorSessionId);
  };

  const handleTrainingBarClick = (state: any) => {
    const payload = state?.activePayload?.[0]?.payload;
    if (!payload) return;
    openReport(payload.behaviorSessionId);
  };

  // 处理能力趋势图数据
  const getAbilityTrendData = () => {
    if (!abilitiesHistory.length) return [];

    // 获取所有能力类型
    const allAbilities = new Set<string>();
    abilitiesHistory.forEach(session => {
      session.abilities.forEach((ability: any) => {
        if (ability.subject) {
          allAbilities.add(ability.subject);
        }
      });
    });

    // 构建数据
    return abilitiesHistory.map(session => {
      const dataPoint: any = {
        date: session.date ? new Date(session.date).toLocaleDateString('zh-CN', {
          month: '2-digit',
          day: '2-digit'
        }) : ''
      };
      session.abilities.forEach((ability: any) => {
        if (ability.subject) {
          dataPoint[ability.subject] = ability.score;
        }
      });
      return dataPoint;
    });
  };

  // 处理训练记录堆叠柱状图数据（一次训练一根柱）
  const getTrainingBarData = () => {
    if (!trainingSessions.length) return [];

    const dateCounts: Record<string, number> = {};
    trainingSessions.forEach((session) => {
      dateCounts[session.date] = (dateCounts[session.date] || 0) + 1;
    });

    return trainingSessions.map((session) => {
      const dateLabel = session.date
        ? new Date(session.date).toLocaleDateString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
          })
        : '';
      const timeLabel = session.start_time
        ? session.start_time.slice(0, 5)
        : '';
      const label =
        (dateCounts[session.date] || 0) > 1 && timeLabel
          ? `${dateLabel} ${timeLabel}`
          : dateLabel;

      const dataPoint: any = {
        label,
        fullDate: session.date,
        startTime: session.start_time,
        behaviorSessionId: session.behavior_session_id,
        overallScore: session.overall_score,
        reportStatus: session.report_status,
      };
      COURSE_SERIES.forEach((course) => {
        dataPoint[course] = 0;
      });
      session.training_details.forEach((detail) => {
        if (detail.course_type_name) {
          dataPoint[detail.course_type_name] = detail.count;
        }
      });
      return dataPoint;
    });
  };

  // 切换能力显示/隐藏
  const toggleAbility = (abilityName: string) => {
    const newHidden = new Set(hiddenAbilities);
    if (newHidden.has(abilityName)) {
      newHidden.delete(abilityName);
    } else {
      newHidden.add(abilityName);
    }
    setHiddenAbilities(newHidden);
  };

  // 处理头像上传
  const handleAvatarUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // 检查文件类型
      if (!file.type.startsWith('image/')) {
        setAddStudentError('请上传图片文件');
        return;
      }
      
      // 检查文件大小（限制为2MB）
      if (file.size > 2 * 1024 * 1024) {
        setAddStudentError('图片大小不能超过2MB');
        return;
      }

      const reader = new FileReader();
      reader.onloadend = () => {
        const base64String = reader.result as string;
        setNewStudent({ ...newStudent, avatar: base64String });
        setAvatarPreview(base64String);
      };
      reader.readAsDataURL(file);
    }
  };

  // 移除头像
  const handleRemoveAvatar = () => {
    setNewStudent({ ...newStudent, avatar: null });
    setAvatarPreview(null);
  };

  // 创建新学生
  const handleCreateStudent = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // 验证必填字段
    if (!newStudent.name.trim()) {
      setAddStudentError('姓名不能为空');
      return;
    }
    
    const age = parseInt(newStudent.age);
    if (!newStudent.age || isNaN(age) || age < 0 || age > 18) {
      setAddStudentError('请输入有效的年龄（0-18岁）');
      return;
    }

    setIsAddingStudent(true);
    setAddStudentError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/students`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newStudent.name.trim(),
          age: age,
          preference: newStudent.preference.trim() || null,
          teacher: newStudent.teacher.trim() || null,
          screening: newStudent.screening.trim() || null,
          avatar: newStudent.avatar,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        // 创建成功，刷新学生列表
        await fetchStudents();
        // 选中新创建的学生
        if (data.student) {
          onSelectStudent(data.student.id.toString());
          loadStudentDetail(data.student.id);
        }
        // 关闭对话框并重置表单
        setShowAddStudentDialog(false);
        setNewStudent({
          name: '',
          age: '',
          preference: '',
          teacher: '',
          screening: '',
          avatar: null,
        });
        setAvatarPreview(null);
      } else {
        setAddStudentError(data.error || '创建学生失败，请重试');
      }
    } catch (err) {
      console.error('创建学生失败:', err);
      setAddStudentError('网络错误，请检查服务器连接');
    } finally {
      setIsAddingStudent(false);
    }
  };

  const currentStudentId = selectedStudent
    ? parseInt(selectedStudent)
    : students[0]?.id;

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  if (students.length === 0) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-600 mb-4">暂无学生数据</p>
          <p className="text-sm text-gray-500">
            请先运行 python database/generate_sample_data.py 生成测试数据
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex h-screen overflow-hidden">
      {/* 左侧学生列表 */}
      <div className="w-80 bg-white border-r border-gray-200 flex flex-col h-full">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-gray-900 flex items-center gap-2">
            <User className="w-6 h-6" />
            学生列表
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto p-6 pt-4">
          <div className="space-y-3">
            {students.map(student => (
              <button
                key={student.id}
                onClick={() => {
                  onSelectStudent(student.id.toString());
                  loadStudentDetail(student.id);
                }}
                disabled={loadingDetail}
                className={`w-full flex items-center gap-4 p-4 rounded-xl transition-all ${
                  currentStudentId === student.id
                    ? 'bg-indigo-50 border-2 border-indigo-500'
                    : 'bg-gray-50 border-2 border-transparent hover:bg-gray-100'
                } ${loadingDetail ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <StudentAvatar src={student.avatar} name={student.name} size="md" />
                <span className="text-gray-900">{student.name}</span>
              </button>
            ))}
            
            {/* 添加儿童按钮 */}
            <button
              onClick={() => {
                setShowAddStudentDialog(true);
                setAddStudentError(null);
              }}
              className="w-full flex items-center justify-center p-4 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 hover:bg-gray-100 hover:border-indigo-400 transition-all"
            >
              <Plus className="w-8 h-8 text-gray-400" strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>

      {/* 右侧学生信息 */}
      <div className="flex-1 overflow-y-auto h-full">
        <div className="p-8 pb-32">
        {loadingDetail ? (
          <div className="flex items-center justify-center h-64">
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
              <p className="text-gray-600">加载学生详情...</p>
            </div>
          </div>
        ) : currentStudent ? (
          <>
            <h1 className="text-gray-900 mb-8 text-2xl font-semibold">
              {currentStudent.name} - 学生档案
            </h1>

            {/* 顶部面板：基础信息和筛查结果 */}
            <div className="grid grid-cols-2 gap-6 mb-6">
              {/* 基础信息卡片 */}
              <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-200">
                <h3 className="text-gray-900 mb-4 flex items-center gap-2">
                  <UserCircle className="w-5 h-5 text-indigo-600" />
                  基础信息
                </h3>
                <div className="space-y-3">
                  <div className="flex items-center gap-4">
                    <StudentAvatar
                      src={currentStudent.avatar}
                      name={currentStudent.name}
                      size="lg"
                    />
                    <div>
                      <div className="text-lg font-semibold text-gray-900">
                        {currentStudent.name}
                      </div>
                      {currentStudent.age && (
                        <div className="text-gray-600">{currentStudent.age}岁</div>
                      )}
                    </div>
                  </div>
                  <div className="pt-3 space-y-2 border-t border-gray-200">
                    {currentStudent.preference && (
                      <div className="flex justify-between">
                        <span className="text-gray-600">偏好物：</span>
                        <span className="text-gray-900">{currentStudent.preference}</span>
                      </div>
                    )}
                    {currentStudent.teacher && (
                      <div className="flex justify-between">
                        <span className="text-gray-600">负责老师：</span>
                        <span className="text-gray-900">{currentStudent.teacher}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* 筛查 / 干预建议卡片 */}
              <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-200 flex flex-col min-h-[220px]">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <h3 className="text-gray-900 flex items-center gap-2">
                    <FileText className="w-5 h-5 text-indigo-600" />
                    {infoPanelTab === 'screening' ? '初步筛查' : '最新干预建议'}
                  </h3>
                  <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                      type="button"
                      onClick={() => setInfoPanelTab('screening')}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        infoPanelTab === 'screening'
                          ? 'bg-white text-indigo-600 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      初步筛查
                    </button>
                    <button
                      type="button"
                      onClick={() => setInfoPanelTab('intervention')}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        infoPanelTab === 'intervention'
                          ? 'bg-white text-indigo-600 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      最新干预建议
                    </button>
                  </div>
                </div>

                <div className="flex-1 min-h-0">
                  {infoPanelTab === 'screening' ? (
                    <p className="text-gray-700 leading-relaxed">
                      {currentStudent.screening || '暂无筛查信息'}
                    </p>
                  ) : intervention && intervention.recommendations.length > 0 ? (
                    <div className="space-y-3 max-h-40 overflow-y-auto pr-1">
                      {intervention.analysis && (
                        <p className="text-sm text-gray-600 leading-relaxed">
                          {intervention.analysis}
                        </p>
                      )}
                      {intervention.recommendations.map((item, idx) => (
                        <div key={idx} className="border-t border-gray-100 pt-2 first:border-0 first:pt-0">
                          <div className="text-sm font-semibold text-gray-900">{item.title}</div>
                          <p className="text-sm text-gray-600 leading-relaxed mt-0.5">{item.body}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-500 leading-relaxed">
                      完成一次完整训练并生成报告后，将在此显示干预建议
                    </p>
                  )}
                </div>

                {infoPanelTab === 'intervention' && (
                  <div className="mt-4 pt-3 border-t border-gray-100">
                    <button
                      type="button"
                      disabled={!intervention?.behavior_session_id}
                      onClick={() => openReport(intervention?.behavior_session_id)}
                      className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:text-indigo-700 disabled:text-gray-400 disabled:cursor-not-allowed"
                    >
                      <ExternalLink className="w-4 h-4" />
                      查看最新评估报告
                    </button>
                  </div>
                )}
              </div>
            </div>

            {reportHint && (
              <div className="mb-4 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                {reportHint}
              </div>
            )}

            {/* 核心数据面板：能力分析 + 训练记录 并排 */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {/* 能力分析板块 */}
              <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-200">
                <div className="flex items-center justify-between mb-4 gap-2">
                  <h3 className="text-gray-900 flex items-center gap-2">
                    <Activity className="w-5 h-5 text-indigo-600" />
                    能力分析
                  </h3>
                  <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                      type="button"
                      onClick={() => setAbilityView('radar')}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        abilityView === 'radar'
                          ? 'bg-white text-indigo-600 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      当前能力
                    </button>
                    <button
                      type="button"
                      onClick={() => setAbilityView('trend')}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        abilityView === 'trend'
                          ? 'bg-white text-indigo-600 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      发展趋势
                    </button>
                  </div>
                </div>

                {abilityView === 'radar' ? (
                  currentStudent.abilities && currentStudent.abilities.length > 0 ? (
                    <div>
                      <ResponsiveContainer width="100%" height={280}>
                        <RadarChart data={currentStudent.abilities}>
                          <PolarGrid />
                          <PolarAngleAxis
                            dataKey="subject"
                            tick={{ fill: '#6b7280', fontSize: 11 }}
                          />
                          <PolarRadiusAxis
                            angle={90}
                            domain={[0, 100]}
                            tick={{ fill: '#6b7280', fontSize: 10 }}
                          />
                          <Radar
                            name="能力值"
                            dataKey="score"
                            stroke="#4f46e5"
                            fill="#4f46e5"
                            fillOpacity={0.6}
                          />
                        </RadarChart>
                      </ResponsiveContainer>
                      {currentStudent.imitation_placeholder !== false && (
                        <p className="text-xs text-gray-400 text-center mt-1">
                          「模仿」暂为占位参考分（60）
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="h-[280px] flex items-center justify-center text-gray-500">
                      暂无能力数据
                    </div>
                  )
                ) : abilitiesHistory.length > 0 && currentStudent.abilities.length > 0 ? (
                  <div>
                    <div className="mb-3 flex flex-wrap gap-2">
                      {currentStudent.abilities.map((ability, index) => (
                        <button
                          key={ability.subject}
                          type="button"
                          onClick={() => toggleAbility(ability.subject)}
                          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                            hiddenAbilities.has(ability.subject)
                              ? 'bg-gray-200 text-gray-500 line-through'
                              : 'bg-indigo-50 text-indigo-600'
                          }`}
                          style={{
                            backgroundColor: hiddenAbilities.has(ability.subject)
                              ? '#e5e7eb'
                              : `${ABILITY_COLORS[index % ABILITY_COLORS.length]}20`,
                            color: hiddenAbilities.has(ability.subject)
                              ? '#6b7280'
                              : ABILITY_COLORS[index % ABILITY_COLORS.length],
                          }}
                        >
                          {ability.subject}
                        </button>
                      ))}
                    </div>
                    <ResponsiveContainer width="100%" height={280}>
                      <LineChart data={getAbilityTrendData()}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} />
                        <YAxis domain={[0, 100]} tick={{ fill: '#6b7280', fontSize: 11 }} />
                        <Tooltip />
                        <Legend />
                        {currentStudent.abilities.map((ability, index) => {
                          if (hiddenAbilities.has(ability.subject)) return null;
                          return (
                            <Line
                              key={ability.subject}
                              type="monotone"
                              dataKey={ability.subject}
                              stroke={ABILITY_COLORS[index % ABILITY_COLORS.length]}
                              strokeWidth={2}
                              dot={{ r: 3 }}
                              name={ability.subject}
                            />
                          );
                        })}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-[280px] flex items-center justify-center text-gray-500">
                    暂无历史能力数据
                  </div>
                )}
              </div>

              {/* 训练记录板块 */}
              <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-200">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="text-gray-900 flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-indigo-600" />
                    训练记录
                  </h3>
                  <p className="text-xs text-gray-400 text-right leading-snug">
                    点击柱状图查看该次评估报告
                  </p>
                </div>
                {trainingSessions.length > 0 ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart
                      data={getTrainingBarData()}
                      style={{ cursor: 'pointer' }}
                      onClick={handleTrainingBarClick}
                    >
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="label" tick={{ fill: '#6b7280', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} allowDecimals={false} />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const row = payload[0].payload;
                            return (
                              <div className="bg-white p-3 border border-gray-200 rounded-lg shadow-lg">
                                <p className="font-semibold mb-1">{row.label}</p>
                                {row.overallScore != null && (
                                  <p className="text-xs text-gray-500 mb-2">
                                    综合分：{row.overallScore}
                                    {row.reportStatus ? ` · ${row.reportStatus}` : ''}
                                  </p>
                                )}
                                {payload.map((entry: any, index: number) => (
                                  <p
                                    key={index}
                                    className="text-sm"
                                    style={{ color: entry.color }}
                                  >
                                    {entry.name}: {entry.value}次
                                  </p>
                                ))}
                                <p className="text-sm font-semibold mt-2 text-gray-700">
                                  总计:{' '}
                                  {payload.reduce(
                                    (sum: number, entry: any) => sum + (Number(entry.value) || 0),
                                    0
                                  )}{' '}
                                  次
                                </p>
                                <p className="text-xs text-indigo-600 mt-2">
                                  {row.behaviorSessionId
                                    ? '点击查看评估报告'
                                    : '该记录无关联评估报告'}
                                </p>
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Legend />
                      {COURSE_SERIES.map((course, index) => (
                        <Bar
                          key={course}
                          dataKey={course}
                          stackId="a"
                          fill={COURSE_COLORS[index % COURSE_COLORS.length]}
                          name={course}
                          cursor="pointer"
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-[280px] flex items-center justify-center text-gray-500">
                    暂无训练记录
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-64">
            <p className="text-gray-600">请选择一个学生</p>
          </div>
        )}
        </div>
      </div>

      {/* 左下角固定用户信息框 */}
      <div className="fixed bottom-8 left-8 z-10">
        <div className="relative">
          <button
            onClick={() => setShowLogoutMenu(!showLogoutMenu)}
            className="flex items-center gap-3 p-4 bg-white hover:bg-gray-50 rounded-xl border-2 border-gray-200 shadow-lg transition-all"
          >
            <AdultAvatar
              src={null}
              name={currentTeacher?.real_name || currentTeacher?.username || '教师'}
              size="sm"
            />
            <div className="text-left">
              <div className="text-gray-900 font-medium">
                {currentTeacher?.real_name || currentTeacher?.username || '教师账号'}
              </div>
              <div className="text-gray-500 text-sm">
                {currentTeacher?.username || '已登录'}
              </div>
            </div>
            <ChevronDown
              className={`w-5 h-5 text-gray-400 transition-transform ${
                showLogoutMenu ? 'rotate-180' : ''
              }`}
            />
          </button>

          {/* 退出登录菜单 */}
          {showLogoutMenu && (
            <div className="absolute bottom-full left-0 mb-2 bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden min-w-full">
              <button
                onClick={onLogout}
                className="w-full flex items-center gap-3 p-4 hover:bg-red-50 text-red-600 transition-colors"
              >
                <LogOut className="w-5 h-5" />
                <span>退出登录</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 右下角固定按钮 */}
      <div className="fixed bottom-8 right-8 flex gap-4 z-10">
        <button
          onClick={onStartAssessment}
          disabled={preparing || !selectedStudent}
          className="px-8 py-4 bg-green-600 hover:bg-green-700 disabled:bg-green-400 disabled:cursor-not-allowed text-white rounded-xl shadow-lg transition-colors"
        >
          {preparing ? '正在准备录制…' : '开始评估'}
        </button>
        <button
          onClick={onStartTraining}
          disabled={preparing || !selectedStudent}
          className="px-8 py-4 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 disabled:cursor-not-allowed text-white rounded-xl shadow-lg transition-colors"
        >
          {preparing ? '正在准备录制…' : '开始训练'}
        </button>
      </div>

      {/* 添加学生对话框 */}
      <Dialog open={showAddStudentDialog} onOpenChange={setShowAddStudentDialog}>
        <DialogContent className="sm:max-w-md max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-semibold text-gray-900">
              添加儿童
            </DialogTitle>
            <DialogDescription className="text-gray-600">
              请填写儿童的基本信息
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleCreateStudent} className="space-y-4">
            {/* 头像上传 */}
            <div>
              <label className="block text-gray-700 mb-2 text-sm">头像</label>
              <div className="flex items-center gap-4">
                <div className="relative">
                  {avatarPreview ? (
                    <div className="relative">
                      <img
                        src={avatarPreview}
                        alt="头像预览"
                        className="w-20 h-20 rounded-full object-cover border-2 border-gray-200"
                      />
                      <button
                        type="button"
                        onClick={handleRemoveAvatar}
                        className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 text-white rounded-full flex items-center justify-center hover:bg-red-600 transition-colors"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="w-20 h-20 rounded-full bg-gray-100 border-2 border-gray-200 flex items-center justify-center">
                      <UserCircle className="w-10 h-10 text-gray-400" />
                    </div>
                  )}
                </div>
                <label className="flex-1">
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleAvatarUpload}
                    className="hidden"
                  />
                  <div className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors flex items-center justify-center gap-2">
                    <Upload className="w-4 h-4 text-gray-600" />
                    <span className="text-sm text-gray-700">上传头像</span>
                  </div>
                </label>
              </div>
            </div>

            {/* 姓名 */}
            <div>
              <label htmlFor="add-student-name" className="block text-gray-700 mb-2 text-sm">
                姓名 <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="add-student-name"
                  type="text"
                  value={newStudent.name}
                  onChange={(e) => setNewStudent({ ...newStudent, name: e.target.value })}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  placeholder="请输入姓名"
                  required
                />
              </div>
            </div>

            {/* 年龄 */}
            <div>
              <label htmlFor="add-student-age" className="block text-gray-700 mb-2 text-sm">
                年龄 <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <UserCircle className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="add-student-age"
                  type="number"
                  min="0"
                  max="18"
                  value={newStudent.age}
                  onChange={(e) => setNewStudent({ ...newStudent, age: e.target.value })}
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  placeholder="请输入年龄"
                  required
                />
              </div>
            </div>

            {/* 偏好物 */}
            <div>
              <label htmlFor="add-student-preference" className="block text-gray-700 mb-2 text-sm">
                偏好物
              </label>
              <input
                id="add-student-preference"
                type="text"
                value={newStudent.preference}
                onChange={(e) => setNewStudent({ ...newStudent, preference: e.target.value })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="请输入偏好物（可选）"
              />
            </div>

            {/* 负责老师 */}
            <div>
              <label htmlFor="add-student-teacher" className="block text-gray-700 mb-2 text-sm">
                负责老师
              </label>
              <input
                id="add-student-teacher"
                type="text"
                value={newStudent.teacher}
                onChange={(e) => setNewStudent({ ...newStudent, teacher: e.target.value })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="请输入负责老师（可选）"
              />
            </div>

            {/* 初步筛查 */}
            <div>
              <label htmlFor="add-student-screening" className="block text-gray-700 mb-2 text-sm">
                初步筛查
              </label>
              <textarea
                id="add-student-screening"
                value={newStudent.screening}
                onChange={(e) => setNewStudent({ ...newStudent, screening: e.target.value })}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
                placeholder="请输入初步筛查或简介（可选）"
                rows={3}
              />
            </div>

            {/* 错误提示 */}
            {addStudentError && (
              <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
                <X className="w-5 h-5 text-red-600 flex-shrink-0" />
                <p className="text-sm text-red-600">{addStudentError}</p>
              </div>
            )}

            <DialogFooter className="gap-2 sm:gap-0">
              <button
                type="button"
                onClick={() => {
                  setShowAddStudentDialog(false);
                  setAddStudentError(null);
                  setNewStudent({
                    name: '',
                    age: '',
                    preference: '',
                    teacher: '',
                    screening: '',
                    avatar: null,
                  });
                  setAvatarPreview(null);
                }}
                className="px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                disabled={isAddingStudent}
              >
                取消
              </button>
              <button
                type="submit"
                disabled={isAddingStudent}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center"
              >
                {isAddingStudent ? (
                  <>
                    <Loader2 className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" />
                    创建中...
                  </>
                ) : (
                  '创建'
                )}
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
