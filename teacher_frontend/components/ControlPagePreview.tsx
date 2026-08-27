import { ControlPage, Course } from './ControlPage';

const PREVIEW_COURSES: Course[] = [
  {
    id: 2,
    title: '命名',
    type: 'naming',
    question: '这是什么？',
    praise: '说得很好！',
    items: [
      { id: 201, name: '苹果', type: 'naming', speechTarget: '苹果' },
      { id: 202, name: '香蕉', type: 'naming', speechTarget: '香蕉' },
    ],
  },
  {
    id: 3,
    title: '拟声',
    type: 'onomatopoeia',
    question: '听一听，这是什么声音？',
    praise: '模仿得很像！',
    items: [
      { id: 301, name: '小狗叫声', type: 'onomatopoeia', speechTarget: '汪汪' },
      { id: 302, name: '小猫叫声', type: 'onomatopoeia', speechTarget: '喵喵' },
    ],
  },
  {
    id: 9,
    title: '配对',
    type: 'pairing',
    file: 'pairing/index.html',
    items: [{ id: 901, name: '水果配对', type: 'pairing' }],
  },
  {
    id: 10,
    title: '排序',
    type: 'ordering',
    file: 'ordering/index.html',
    items: [{ id: 1001, name: '大小排序', type: 'ordering' }],
  },
  {
    id: 11,
    title: '社交',
    type: 'social',
    items: [
      { id: 1101, name: '打招呼', type: 'social', config: { socialRole: 'greeting' } },
      { id: 1102, name: '再见', type: 'social', config: { socialRole: 'farewell' } },
    ],
  },
];

const PREVIEW_SELECTION = PREVIEW_COURSES.map((course) => ({
  categoryId: course.type,
  courseId: String(course.id),
}));

export function ControlPagePreview() {
  return (
    <ControlPage
      previewMode
      previewCourses={PREVIEW_COURSES}
      selectedCourses={PREVIEW_SELECTION}
      selectedStudent="1001"
      mode="training"
      onBack={() => undefined}
      onFinish={() => undefined}
    />
  );
}
