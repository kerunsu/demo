import { useState, useRef, useCallback, useEffect } from 'react';
import { io, Socket } from 'socket.io-client';
import { LoginPage } from './components/LoginPage';
import { StudentInfoPage } from './components/StudentInfoPage';
import { CourseSelectionPage } from './components/CourseSelectionPage';
import { ControlPage } from './components/ControlPage';
import { ReportPage } from './components/ReportPage';
import {
  TrainingReadinessDialog,
  ReadinessCourseItem,
} from './components/TrainingReadinessDialog';

type PageType = 'login' | 'studentInfo' | 'courseSelection' | 'control' | 'report';
const PAGE_TYPES = new Set<PageType>([
  'login',
  'studentInfo',
  'courseSelection',
  'control',
  'report',
]);

interface Teacher {
  id: number;
  username: string;
  real_name: string | null;
  email: string | null;
  phone: string | null;
}

interface CourseSel {
  categoryId: string;
  courseId: string;
}

/** 登录身份 */
const STORAGE_TEACHER = 'teacherSession';
/** 当前页与训练上下文（刷新可恢复） */
const STORAGE_NAV = 'teacherAppNav';

interface NavSnapshot {
  currentPage: PageType;
  selectedStudent: string | null;
  assessmentMode: boolean;
  selectedCourses: CourseSel[];
  preparedTrainingSessionId: string | null;
  reportTrainingSessionId: string | null;
  readinessPassed: boolean;
}

function createRequestId(prefix: string): string {
  const randomId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomId}`;
}

function asOptionalId(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

function loadTeacherSession(): Teacher | null {
  try {
    const raw = localStorage.getItem(STORAGE_TEACHER);
    if (!raw) return null;
    const t = JSON.parse(raw);
    if (!t || typeof t.id !== 'number' || !t.username) return null;
    return t as Teacher;
  } catch {
    return null;
  }
}

function saveTeacherSession(teacher: Teacher | null) {
  try {
    if (!teacher) {
      localStorage.removeItem(STORAGE_TEACHER);
      return;
    }
    localStorage.setItem(STORAGE_TEACHER, JSON.stringify(teacher));
  } catch (error) {
    console.warn('无法持久化教师登录状态:', error);
  }
}

function sanitizeNav(raw: unknown, hasTeacher: boolean): NavSnapshot {
  const fallback: NavSnapshot = {
    currentPage: hasTeacher ? 'studentInfo' : 'login',
    selectedStudent: null,
    assessmentMode: false,
    selectedCourses: [],
    preparedTrainingSessionId: null,
    reportTrainingSessionId: null,
    readinessPassed: false,
  };
  if (!hasTeacher) return { ...fallback, currentPage: 'login' };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fallback;

  const snapshot = raw as Partial<NavSnapshot>;
  const rawPage = snapshot.currentPage;
  let page: PageType =
    typeof rawPage === 'string' && PAGE_TYPES.has(rawPage as PageType)
      ? (rawPage as PageType)
      : 'studentInfo';
  const student = asOptionalId(snapshot.selectedStudent);
  const courses = Array.isArray(snapshot.selectedCourses)
    ? snapshot.selectedCourses.filter(
        (course): course is CourseSel =>
          Boolean(
            course &&
              typeof course === 'object' &&
              typeof course.categoryId === 'string' &&
              course.categoryId.trim() &&
              typeof course.courseId === 'string' &&
              course.courseId.trim(),
          ),
      )
    : [];
  const prepared = asOptionalId(snapshot.preparedTrainingSessionId);
  const reportTs = asOptionalId(snapshot.reportTrainingSessionId);
  let readinessPassed = Boolean(snapshot.readinessPassed);

  // 就绪门弹窗不持久化：刷新时若卡在门禁，回到选课页
  if (page === 'control') {
    if (!student || courses.length === 0) {
      page = student ? 'courseSelection' : 'studentInfo';
      readinessPassed = false;
    } else {
      // 已在控制页：视为已过就绪门，避免刷新后无法进课
      readinessPassed = true;
    }
  } else if (page === 'courseSelection' && !student) {
    page = 'studentInfo';
  } else if (page === 'report' && !reportTs) {
    page = 'studentInfo';
  } else if (page === 'login') {
    page = 'studentInfo';
  }

  return {
    currentPage: page,
    selectedStudent: student,
    assessmentMode: Boolean(snapshot.assessmentMode),
    selectedCourses: courses,
    preparedTrainingSessionId: prepared,
    reportTrainingSessionId: reportTs,
    readinessPassed,
  };
}

function loadNavSnapshot(hasTeacher: boolean): NavSnapshot {
  try {
    const raw = localStorage.getItem(STORAGE_NAV);
    if (!raw) return sanitizeNav(null, hasTeacher);
    return sanitizeNav(JSON.parse(raw), hasTeacher);
  } catch {
    return sanitizeNav(null, hasTeacher);
  }
}

function resolveSocketUrl(): string {
  const isDevelopment = import.meta.env.DEV;
  const isViteDevServer = window.location.port && window.location.port !== '8080';
  if (isDevelopment && isViteDevServer) {
    return window.location.origin;
  }
  return import.meta.env.VITE_SOCKET_URL || window.location.origin;
}

function ensureTeacherSocket(existing: Socket | null): Socket {
  const bindPresence = (socket: Socket) => {
    const emitPresence = () => {
      socket.emit('client_presence', { role: 'teacher', ts: Date.now() });
    };
    if (!(socket as any).__presenceBound) {
      socket.on('connect', emitPresence);
      (socket as any).__presenceBound = true;
    }
    if (!(socket as any).__presenceTimer) {
      (socket as any).__presenceTimer = window.setInterval(() => {
        if (socket.connected) emitPresence();
      }, 10000);
    }
    if (socket.connected) emitPresence();
  };

  if (existing?.connected) {
    bindPresence(existing);
    return existing;
  }
  if (existing) {
    bindPresence(existing);
    existing.connect();
    return existing;
  }
  const socket = io(resolveSocketUrl(), {
    // Establish with HTTP polling first, then upgrade. A websocket-first
    // connection can stall behind Vite or LAN proxies before the event is sent.
    transports: ['polling', 'websocket'],
    tryAllTransports: true,
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: Infinity,
    path: '/socket.io/',
    timeout: 20000,
    withCredentials: true,
  });
  bindPresence(socket);
  return socket;
}

function disposeTeacherSocket(socket: Socket | null): void {
  if (!socket) return;
  const presenceTimer = (socket as any).__presenceTimer;
  if (presenceTimer) {
    window.clearInterval(presenceTimer);
    (socket as any).__presenceTimer = null;
  }
  socket.disconnect();
}

const initialTeacher = loadTeacherSession();
const initialNav = loadNavSnapshot(!!initialTeacher);

export default function App() {
  const [currentPage, setCurrentPage] = useState<PageType>(initialNav.currentPage);
  const [selectedStudent, setSelectedStudent] = useState<string | null>(initialNav.selectedStudent);
  const [assessmentMode, setAssessmentMode] = useState(initialNav.assessmentMode);
  const [selectedCourses, setSelectedCourses] = useState<CourseSel[]>(initialNav.selectedCourses);
  const [currentTeacher, setCurrentTeacher] = useState<Teacher | null>(initialTeacher);
  const [reportTrainingSessionId, setReportTrainingSessionId] = useState<string | null>(
    initialNav.reportTrainingSessionId
  );
  const [preparedTrainingSessionId, setPreparedTrainingSessionId] = useState<string | null>(
    initialNav.preparedTrainingSessionId
  );
  const [preparing, setPreparing] = useState(false);
  const [readinessOpen, setReadinessOpen] = useState(false);
  const [readinessItems, setReadinessItems] = useState<ReadinessCourseItem[]>([]);
  const [readinessPassed, setReadinessPassed] = useState(initialNav.readinessPassed);
  const prepareSocketRef = useRef<Socket | null>(null);
  const prepareRequestRef = useRef<{
    requestId: string;
    cancel: (reason: string) => void;
  } | null>(null);

  // localStorage is navigation cache only. The signed server session is the
  // source of truth for teacher identity after every refresh.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/teacher/session', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error('teacher_session_expired');
        return response.json();
      })
      .then((data) => {
        if (cancelled || !data?.authenticated || !data?.teacher) return;
        setCurrentTeacher(data.teacher as Teacher);
        saveTeacherSession(data.teacher as Teacher);
      })
      .catch(() => {
        if (cancelled) return;
        setCurrentTeacher(null);
        saveTeacherSession(null);
        setCurrentPage('login');
        try {
          localStorage.removeItem(STORAGE_NAV);
        } catch {}
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 持久化登录 + 导航/训练上下文
  useEffect(() => {
    saveTeacherSession(currentTeacher);
  }, [currentTeacher]);

  // Keep exactly one teacher connection. App owns presence outside the live
  // classroom; ControlPage owns the connection while teaching.
  useEffect(() => {
    if (!currentTeacher) return;
    if (currentPage === 'control') {
      disposeTeacherSocket(prepareSocketRef.current);
      prepareSocketRef.current = null;
      return;
    }
    prepareSocketRef.current = ensureTeacherSocket(prepareSocketRef.current);
  }, [currentTeacher?.id, currentPage]);

  useEffect(() => {
    if (!currentTeacher) {
      try {
        localStorage.removeItem(STORAGE_NAV);
      } catch (error) {
        console.warn('无法清理教师端导航状态:', error);
      }
      return;
    }
    const snap: NavSnapshot = {
      currentPage,
      selectedStudent,
      assessmentMode,
      selectedCourses,
      preparedTrainingSessionId,
      reportTrainingSessionId,
      readinessPassed,
    };
    try {
      localStorage.setItem(STORAGE_NAV, JSON.stringify(snap));
    } catch (error) {
      console.warn('无法持久化教师端导航状态:', error);
    }
  }, [
    currentTeacher,
    currentPage,
    selectedStudent,
    assessmentMode,
    selectedCourses,
    preparedTrainingSessionId,
    reportTrainingSessionId,
    readinessPassed,
  ]);

  const handleLogin = (teacher: Teacher) => {
    setCurrentTeacher(teacher);
    saveTeacherSession(teacher);
    setCurrentPage('studentInfo');
  };

  const handleLogout = () => {
    prepareRequestRef.current?.cancel('教师已退出登录');
    setCurrentPage('login');
    setSelectedStudent(null);
    setSelectedCourses([]);
    setCurrentTeacher(null);
    setReportTrainingSessionId(null);
    setPreparedTrainingSessionId(null);
    setReadinessOpen(false);
    setReadinessItems([]);
    setReadinessPassed(false);
    saveTeacherSession(null);
    try {
      localStorage.removeItem(STORAGE_NAV);
    } catch (error) {
      console.warn('无法清理教师端导航状态:', error);
    }
    if (prepareSocketRef.current) {
      disposeTeacherSocket(prepareSocketRef.current);
      prepareSocketRef.current = null;
    }
    void fetch('/api/teacher/logout', {
      method: 'POST',
      credentials: 'include',
    }).catch(() => undefined);
  };

  const prepareTraining = useCallback((mode: 'assessment' | 'training'): Promise<string> => {
    if (prepareRequestRef.current) {
      return Promise.reject(new Error('训练正在准备中，请勿重复操作'));
    }

    return new Promise((resolve, reject) => {
      if (!selectedStudent) {
        reject(new Error('请先选择儿童'));
        return;
      }
      const studentId = parseInt(selectedStudent, 10);
      if (!Number.isFinite(studentId)) {
        reject(new Error('儿童标识无效，请重新选择'));
        return;
      }
      const socket = ensureTeacherSocket(prepareSocketRef.current);
      prepareSocketRef.current = socket;
      const requestId = createRequestId('prepare-training');
      let lastConnectionError = '';

      let settled = false;
      const finish = (err: Error | null, trainingSessionId?: string) => {
        if (settled) return;
        settled = true;
        socket.off('prepare_training_ack', onAck);
        socket.off('connect', emitPrepare);
        socket.off('connect_error', onConnectError);
        window.clearTimeout(timer);
        if (prepareRequestRef.current?.requestId === requestId) {
          prepareRequestRef.current = null;
        }
        if (err) reject(err);
        else resolve(trainingSessionId as string);
      };

      const onAck = (data: any) => {
        if (data?.requestId !== requestId) return;
        if (data?.success && data?.trainingSessionId) {
          finish(null, data.trainingSessionId);
        } else {
          finish(new Error(data?.message || data?.error || '准备训练失败'));
        }
      };

      const timer = window.setTimeout(() => {
        const detail = lastConnectionError ? `（${lastConnectionError}）` : '';
        finish(new Error(`准备录制超时，教师端未收到服务器确认${detail}`));
      }, 25000);

      const onConnectError = (error: Error) => {
        lastConnectionError = error?.message || 'Socket 连接失败';
      };

      const emitPrepare = () => {
        socket.emit('prepare_training', {
          studentId,
          mode,
          requestId,
          // 采集模式属于服务端部署配置，不能用 assessment/training 业务模式推断。
          // auto 由服务端按 childMediaMode 决定：agent=strict，browser=legacy。
          preflightMode: 'auto',
        });
      };

      prepareRequestRef.current = {
        requestId,
        cancel: (reason: string) => finish(new Error(reason)),
      };
      socket.on('prepare_training_ack', onAck);
      socket.on('connect', emitPrepare);
      socket.on('connect_error', onConnectError);
      if (socket.connected) {
        emitPrepare();
      } else {
        socket.connect();
      }
    });
  }, [selectedStudent]);

  useEffect(() => {
    return () => {
      prepareRequestRef.current?.cancel('教师端页面已关闭');
      const socket = prepareSocketRef.current;
      if (!socket) return;
      disposeTeacherSocket(socket);
      prepareSocketRef.current = null;
    };
  }, []);

  // 录制被控制台强制关闭后，回到学生选择页重新选择角色和课程。
  // 通过 ref 持有最新 handler，避免闭包捕获首帧状态。
  const handleBackToStudentsRef = useRef<() => void>(() => {});
  useEffect(() => {
    const onForcedStopRestart = () => {
      handleBackToStudentsRef.current();
    };
    window.addEventListener('recording:forced-stop-restart', onForcedStopRestart);
    return () =>
      window.removeEventListener('recording:forced-stop-restart', onForcedStopRestart);
  }, []);

  const cancelPreparedTraining = useCallback(() => {
    const studentId = selectedStudent ? parseInt(selectedStudent, 10) : undefined;
    const socket = prepareSocketRef.current;
    if (socket?.connected && (studentId || preparedTrainingSessionId)) {
      socket.emit('cancel_prepare_training', {
        studentId,
        trainingSessionId: preparedTrainingSessionId || undefined,
      });
    }
    setPreparedTrainingSessionId(null);
  }, [selectedStudent, preparedTrainingSessionId]);

  const handleStartAssessment = async () => {
    if (!selectedStudent) {
      alert('请先选择儿童');
      return;
    }
    setPreparing(true);
    try {
      const ts = await prepareTraining('assessment');
      setPreparedTrainingSessionId(ts);
      setAssessmentMode(true);
      setCurrentPage('courseSelection');
    } catch (e: any) {
      alert(e?.message || String(e));
    } finally {
      setPreparing(false);
    }
  };

  const handleStartTraining = async () => {
    if (!selectedStudent) {
      alert('请先选择儿童');
      return;
    }
    setPreparing(true);
    try {
      const ts = await prepareTraining('training');
      setPreparedTrainingSessionId(ts);
      setAssessmentMode(false);
      setCurrentPage('courseSelection');
    } catch (e: any) {
      alert(e?.message || String(e));
    } finally {
      setPreparing(false);
    }
  };

  const handleStartCourse = async (payload: {
    courses: Array<{ categoryId: string; courseId: string }>;
    items: ReadinessCourseItem[];
  }) => {
    if (!preparedTrainingSessionId) {
      setPreparing(true);
      try {
        const trainingId = await prepareTraining(
          assessmentMode ? 'assessment' : 'training',
        );
        setPreparedTrainingSessionId(trainingId);
      } catch (error: any) {
        alert(error?.message || String(error));
        return;
      } finally {
        setPreparing(false);
      }
    }
    setSelectedCourses(payload.courses);
    setReadinessItems(payload.items || []);
    setReadinessPassed(false);
    // 先打开就绪门，禁止瞬时进入 ControlPage
    const socket = ensureTeacherSocket(prepareSocketRef.current);
    prepareSocketRef.current = socket;
    if (!socket.connected) {
      socket.connect();
    }
    setReadinessOpen(true);
  };

  const handleReadinessEnter = () => {
    setReadinessOpen(false);
    setReadinessPassed(true);
    setCurrentPage('control');
  };

  const handleReadinessCancel = () => {
    setReadinessOpen(false);
    setReadinessPassed(false);
    cancelPreparedTraining();
  };

  const handleReadinessReprepare = useCallback(async () => {
    const trainingId = await prepareTraining(
      assessmentMode ? 'assessment' : 'training',
    );
    setPreparedTrainingSessionId(trainingId);
    return trainingId;
  }, [assessmentMode, prepareTraining]);

  const handleBackToStudents = () => {
    if (currentPage === 'courseSelection') {
      if (readinessOpen && prepareSocketRef.current?.connected) {
        prepareSocketRef.current.emit('readiness_cancel', {
          trainingSessionId: preparedTrainingSessionId || undefined,
          studentId: selectedStudent ? parseInt(selectedStudent, 10) : undefined,
        });
      }
      setReadinessOpen(false);
      cancelPreparedTraining();
    }
    setCurrentPage('studentInfo');
  };
  handleBackToStudentsRef.current = handleBackToStudents;

  const handleBackToCourseSelection = () => {
    setPreparedTrainingSessionId(null);
    setReadinessPassed(false);
    setCurrentPage('courseSelection');
  };

  const handleViewReport = (trainingSessionId: string) => {
    setReportTrainingSessionId(trainingSessionId);
    setPreparedTrainingSessionId(null);
    setReadinessPassed(false);
    setCurrentPage('report');
  };

  const handleFinishToStudents = () => {
    setPreparedTrainingSessionId(null);
    setReadinessPassed(false);
    setCurrentPage('studentInfo');
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {currentPage === 'login' && <LoginPage onLogin={handleLogin} />}
      {currentPage === 'studentInfo' && currentTeacher && (
        <StudentInfoPage
          onStartAssessment={handleStartAssessment}
          onStartTraining={handleStartTraining}
          selectedStudent={selectedStudent}
          onSelectStudent={setSelectedStudent}
          onLogout={handleLogout}
          currentTeacher={currentTeacher}
          preparing={preparing}
          onViewReport={handleViewReport}
        />
      )}
      {currentPage === 'courseSelection' && (
        <CourseSelectionPage
          onStart={handleStartCourse}
          onBack={handleBackToStudents}
          mode={assessmentMode ? 'assessment' : 'training'}
        />
      )}
      {currentPage === 'control' && (
        <ControlPage 
          onBack={handleBackToCourseSelection} 
          onFinish={handleFinishToStudents}
          onViewReport={handleViewReport}
          selectedCourses={selectedCourses}
          selectedStudent={selectedStudent}
          initialTrainingSessionId={preparedTrainingSessionId}
          readinessPassed={readinessPassed}
        />
      )}
      {currentPage === 'report' && reportTrainingSessionId && (
        <ReportPage
          trainingSessionId={reportTrainingSessionId}
          studentName={selectedStudent}
          onBack={handleFinishToStudents}
        />
      )}
      <TrainingReadinessDialog
        open={readinessOpen}
        socket={prepareSocketRef.current}
        studentId={selectedStudent}
        trainingSessionId={preparedTrainingSessionId}
        items={readinessItems}
        onEnter={handleReadinessEnter}
        onCancel={handleReadinessCancel}
        onReprepare={handleReadinessReprepare}
      />
    </div>
  );
}
