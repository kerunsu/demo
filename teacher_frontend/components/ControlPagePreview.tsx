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
    id: 10,
    title: '排序',
    type: 'ordering',
    file: 'ordering/index.html',
    items: [{ id: 1001, name: '大小排序', type: 'ordering' }],
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
