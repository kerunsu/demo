import { useState, useEffect } from 'react';
import { MessageCircle, Blocks, Brain, ArrowLeft, Sparkles } from 'lucide-react';

interface CourseSelectionPageProps {
  onStart: (payload: {
    courses: Array<{ categoryId: string; courseId: string }>;
    items: Array<{
      courseId: string | number;
      itemId: string | number | null;
      courseType: string;
      file?: string;
    }>;
  }) => void;
  onBack: () => void;
  mode: 'assessment' | 'training';
}

// 课程类型映射（英文 -> 中文名称和图标）
const courseTypeMap: Record<string, { name: string; icon: typeof Brain }> = {
  'naming': { name: '命名', icon: MessageCircle },
  'ordering': { name: '排序', icon: Blocks },
};

// 默认图标
const DefaultIcon = Brain;
const DEFAULT_ITEM_IMAGE = 'https://images.unsplash.com/photo-1759159482847-78aadfcbeb85?w=300&h=200&fit=crop';
const PRESET_VIEW_PREFIX = 'course-preset:';

interface CourseItem {
  id: number;
  name: string;
  type: string;
  file?: string;
  icon?: string;
  hint?: string;
  difficulty?: string;
  config?: any;
  speechTarget?: string | null;
}

interface Course {
  id: number;
  title: string;
  type: string;
  question?: string;
  praise?: string;
  file?: string;
  icon?: string;
  items: CourseItem[];
}

interface CourseCategory {
  id: string;
  name: string;
  icon: typeof Brain;
  courses: Course[];
}

interface CoursePreset {
  id: string;
  name: string;
  description: string;
  mode: 'assessment' | 'intervention';
  courseSelections: Array<{
    courseType: string;
    itemIds: number[];
  }>;
  courseTypes: string[];
  courseIds: number[];
  available: boolean;
  missingCourseIds: number[];
  emptyCourseIds: number[];
  isDefault: boolean;
}

interface CoursePresetResponse {
  success: boolean;
  defaultPresetId: string | null;
  defaultPresetIds?: {
    assessment: string | null;
    intervention: string | null;
  };
  presets: CoursePreset[];
}

function selectionForPreset(preset: CoursePreset, allCourses: Course[]) {
  const selected = new Map<string, Set<number>>();
  for (const selection of preset.courseSelections || []) {
    const course = allCourses.find(candidate => candidate.type === selection.courseType);
    if (!course || !selection.itemIds.length) return null;
    const availableIds = new Set(course.items.map(item => item.id));
    if (selection.itemIds.some(itemId => !availableIds.has(itemId))) return null;
    selected.set(course.id.toString(), new Set(selection.itemIds));
  }
  if (selected.size !== preset.courseSelections.length) return null;
  return selected;
}

function presetCourseTypes(preset: CoursePreset) {
  return (preset.courseSelections || []).map(selection => selection.courseType);
}

export function CourseSelectionPage({ onStart, onBack, mode }: CourseSelectionPageProps) {
  const presetMode = mode === 'assessment' ? 'assessment' : 'intervention';
  const [courses, setCourses] = useState<Course[]>([]);
  const [categories, setCategories] = useState<CourseCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedItems, setSelectedItems] = useState<Map<string, Set<number>>>(new Map()); // courseId -> Set<itemId>
  const [presets, setPresets] = useState<CoursePreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [presetError, setPresetError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 从后端获取课程数据
  useEffect(() => {
    const fetchCourses = async () => {
      try {
        setLoading(true);
        const [response, presetResponse] = await Promise.all([
          fetch('/courses'),
          fetch('/api/config/course-presets').catch(() => null),
        ]);
        
        // 检查响应类型
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          const text = await response.text();
          console.error('收到非 JSON 响应:', text.substring(0, 200));
          throw new Error(`服务器返回了非 JSON 响应。请检查后端服务是否正常运行。状态码: ${response.status}`);
        }
        
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `获取课程数据失败 (${response.status})`);
        }
        
        const data: Course[] = await response.json();
        setCourses(data);

        let presetData: CoursePresetResponse | null = null;
        if (presetResponse?.ok) {
          try {
            presetData = await presetResponse.json();
            if (!presetData?.success || !Array.isArray(presetData.presets)) {
              presetData = null;
            }
          } catch (_) {
            presetData = null;
          }
        }
        const matchingPresets = presetData
          ? presetData.presets.filter(preset => (preset.mode || 'assessment') === presetMode)
          : [];
        if (presetData) {
          setPresets(matchingPresets);
          setPresetError(null);
        } else {
          setPresets([]);
          setPresetError('Server 课程预设暂时不可用，仍可手动选择课程。');
        }

        // 按类型分组
        const grouped = new Map<string, Course[]>();
        data.forEach(course => {
          const type = course.type;
          if (!grouped.has(type)) {
            grouped.set(type, []);
          }
          grouped.get(type)!.push(course);
        });

        // 转换为分类数组
        const categoryArray: CourseCategory[] = Array.from(grouped.entries()).map(([type, courses]) => {
          const typeInfo = courseTypeMap[type] || { name: type, icon: DefaultIcon };
          return {
            id: type,
            name: typeInfo.name,
            icon: typeInfo.icon,
            courses: courses
          };
        });

        setCategories(categoryArray);
        const defaultPresetId = presetData?.defaultPresetIds?.[presetMode]
          ?? (presetMode === 'assessment' ? presetData?.defaultPresetId : null);
        if (defaultPresetId) {
          const defaultPreset = matchingPresets.find(preset => preset.id === defaultPresetId);
          const presetItems = defaultPreset ? selectionForPreset(defaultPreset, data) : null;
          if (defaultPreset && presetItems) {
            setSelectedItems(presetItems);
            setSelectedPresetId(defaultPreset.id);
            setSelectedCategory(`${PRESET_VIEW_PREFIX}${defaultPreset.id}`);
            return;
          }
        }
        if (categoryArray.length > 0) {
          setSelectedCategory(categoryArray[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '未知错误');
        console.error('获取课程数据失败:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchCourses();
  }, [mode]);

  const viewedPresetId = selectedCategory.startsWith(PRESET_VIEW_PREFIX)
    ? selectedCategory.slice(PRESET_VIEW_PREFIX.length)
    : '';
  const viewedPreset = presets.find(preset => preset.id === viewedPresetId);
  const currentCategory = viewedPreset
    ? {
        id: `${PRESET_VIEW_PREFIX}${viewedPreset.id}`,
        name: viewedPreset.name,
        icon: Sparkles,
        courses: presetCourseTypes(viewedPreset)
          .map(courseType => courses.find(course => course.type === courseType))
          .filter((course): course is Course => Boolean(course)),
      }
    : categories.find(category => category.id === selectedCategory);
  const selectedPreset = presets.find(preset => preset.id === selectedPresetId);
  const displayGroups: CourseCategory[] = viewedPreset
    ? presetCourseTypes(viewedPreset).map(courseType => {
        const typeInfo = courseTypeMap[courseType] || { name: courseType, icon: DefaultIcon };
        return {
          id: courseType,
          name: typeInfo.name,
          icon: typeInfo.icon,
          courses: courses.filter(course => course.type === courseType),
        };
      })
    : currentCategory ? [currentCategory] : [];

  const applyPreset = (presetId: string) => {
    const preset = presets.find(candidate => candidate.id === presetId);
    if (!preset) return;
    const presetItems = selectionForPreset(preset, courses);
    if (!presetItems) return;
    setSelectedItems(presetItems);
    setSelectedPresetId(preset.id);
    setSelectedCategory(`${PRESET_VIEW_PREFIX}${preset.id}`);
  };

  // 切换课程项的选择状态
  const toggleItem = (courseId: number, itemId: number) => {
    setSelectedPresetId('');
    const newSelected = new Map(selectedItems);
    if (!newSelected.has(courseId.toString())) {
      newSelected.set(courseId.toString(), new Set());
    }
    const itemSet = newSelected.get(courseId.toString())!;
    if (itemSet.has(itemId)) {
      itemSet.delete(itemId);
      if (itemSet.size === 0) {
        newSelected.delete(courseId.toString());
      }
    } else {
      itemSet.add(itemId);
    }
    setSelectedItems(newSelected);
  };

  // 大类是唯一选择单位；内部仍保留 courseId/itemId 供课程执行链使用。
  const toggleCategory = (category: CourseCategory) => {
    const categoryCourses = category.courses.filter(course => course.items.length > 0);
    if (!categoryCourses.length) return;
    setSelectedPresetId('');

    const newSelected = new Map(selectedItems);
    const allSelected = categoryCourses.every(course => {
      const selected = newSelected.get(course.id.toString());
      return selected?.size === course.items.length;
    });
    if (allSelected) {
      categoryCourses.forEach(course => newSelected.delete(course.id.toString()));
    } else {
      categoryCourses.forEach(course => {
        newSelected.set(course.id.toString(), new Set(course.items.map(item => item.id)));
      });
    }
    setSelectedItems(newSelected);
  };

  const isCategorySelected = (category: CourseCategory) => {
    const categoryCourses = category.courses.filter(course => course.items.length > 0);
    return categoryCourses.length > 0 && categoryCourses.every(course => {
      const selected = selectedItems.get(course.id.toString());
      return selected?.size === course.items.length;
    });
  };

  // 获取课程项的选择状态
  const isItemSelected = (courseId: number, itemId: number) => {
    const itemSet = selectedItems.get(courseId.toString());
    return itemSet ? itemSet.has(itemId) : false;
  };

  // 获取选中项的总数
  const getSelectedCount = () => {
    let count = 0;
    selectedItems.forEach(itemSet => {
      count += itemSet.size;
    });
    return count;
  };

  const handleStart = () => {
    if (selectedItems.size === 0) {
      alert('请至少选择一个课程项！');
      return;
    }

    // 保存选中的 itemIds 到 localStorage，供 ControlPage 使用
    const selectedItemsData: Record<string, number[]> = {};
    selectedItems.forEach((itemSet, courseId) => {
      selectedItemsData[courseId] = Array.from(itemSet);
    });
    localStorage.setItem('selectedCourseItems', JSON.stringify(selectedItemsData));

    const coursesArray: Array<{ categoryId: string; courseId: string }> = [];
    const readinessItems: Array<{
      courseId: string | number;
      itemId: string | number | null;
      courseType: string;
      file?: string;
    }> = [];

    selectedItems.forEach((itemSet, courseId) => {
      const course = courses.find((candidate) => String(candidate.id) === String(courseId));
      coursesArray.push({
        categoryId: course?.type || selectedCategory,
        courseId: courseId,
      });
      const courseType = course?.type || '';
      const courseFile = course?.file;
      itemSet.forEach((itemId) => {
        const item = course?.items?.find((it) => Number(it.id) === Number(itemId));
        readinessItems.push({
          courseId,
          itemId,
          courseType,
          file: item?.file || courseFile,
        });
      });
    });

    onStart({ courses: coursesArray, items: readinessItems });
  };

  // 获取图片路径
  const getImageUrl = (path?: string) => {
    if (!path) return DEFAULT_ITEM_IMAGE;
    const normalized = String(path).trim().replace(/\\/g, '/');
    if (/^(https?:|data:|blob:)/i.test(normalized)) return normalized;
    // /courses 同时存在 resources/...、static/resources/... 和 /static/... 旧数据。
    // 统一成单个 /static/ 前缀，避免 /static//static/... 导致图片失败。
    return `/static/${normalized.replace(/^\/+/, '').replace(/^(static\/)+/i, '')}`;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">加载课程数据中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (categories.length === 0) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-600">暂无课程数据</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="bg-gray-50 flex h-screen overflow-hidden"
      data-course-catalog-version="canonical-course-types-v2"
    >
      {/* 左侧课程类别列表 */}
      <div className="w-80 bg-white border-r border-gray-200 flex flex-col h-full">
        <div className="p-6 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ArrowLeft className="w-5 h-5 text-gray-600" />
            </button>
            <h2 className="text-gray-900">课程类别</h2>
          </div>
        </div>
        <div className="p-4 border-b border-gray-200">
          <label htmlFor="course-preset" className="mb-2 flex items-center gap-2 text-xs font-semibold text-gray-600">
            <Sparkles className="h-4 w-4 text-indigo-600" />
            课程预设
          </label>
          <select
            id="course-preset"
            value={selectedPresetId}
            onChange={(event) => {
              const presetId = event.target.value;
              if (presetId) {
                applyPreset(presetId);
              } else {
                setSelectedPresetId('');
                if (viewedPresetId && categories[0]) setSelectedCategory(categories[0].id);
              }
            }}
            className="min-h-11 w-full rounded-xl border border-gray-300 bg-white px-3 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          >
            <option value="">手动选择课程</option>
            {presets.map(preset => (
              <option key={preset.id} value={preset.id} disabled={!preset.available}>
                {preset.name}{preset.isDefault ? `（${presetMode === 'assessment' ? '评估' : '干预'}默认）` : ''}{!preset.available ? '（课点不完整）' : ''}
              </option>
            ))}
          </select>
          <p className={`mt-2 text-xs leading-5 ${presetError ? 'text-amber-700' : 'text-gray-500'}`}>
            {presetError || selectedPreset?.description || `这里只显示${presetMode === 'assessment' ? '评估' : '干预'}预设；选择后严格勾选 Server 中配置的具体课点。`}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-6 pt-4">
          <div className="space-y-3">
          {categories.map(category => {
            const Icon = category.icon;
            return (
              <button
                key={category.id}
                onClick={() => setSelectedCategory(category.id)}
                className={`w-full flex items-center gap-4 p-4 rounded-xl transition-all ${
                  selectedCategory === category.id
                    ? 'bg-indigo-50 border-2 border-indigo-500'
                    : 'bg-gray-50 border-2 border-transparent hover:bg-gray-100'
                }`}
              >
                <Icon className={`w-6 h-6 ${
                  selectedCategory === category.id ? 'text-indigo-600' : 'text-gray-600'
                }`} />
                <span className="text-gray-900">{category.name}</span>
                
              </button>
            );
          })}
          </div>
        </div>
      </div>

      {/* 右侧课程内容 */}
      <div className="flex-1 overflow-y-auto h-full">
        <div className="p-8 pb-32">
        <h1 className="text-gray-900 mb-2">
          {currentCategory?.name || ''} - {mode === 'assessment' ? '评估' : '干预'}内容
        </h1>
        <p className="text-gray-600 mb-8">
          已选择 {getSelectedCount()} 项内容
        </p>

        {displayGroups.length > 0 ? (
          <div className="space-y-6">
            {displayGroups.map(group => {
              const categorySelected = isCategorySelected(group);
              const selectedCount = group.courses.reduce(
                (sum, course) => sum + (selectedItems.get(course.id.toString())?.size || 0),
                0,
              );
              const totalCount = group.courses.reduce((sum, course) => sum + course.items.length, 0);
              const categoryItems = group.courses.flatMap(course =>
                course.items.map(item => ({ course, item })),
              );
              return (
                <div key={group.id} className="bg-white rounded-xl shadow-sm border-2 border-gray-200 overflow-hidden">
                  {/* 大类标题栏 */}
                  <div className="p-4 bg-gray-50 border-b border-gray-200">
                    <div className="flex items-center justify-between">
                      <button
                        type="button"
                        onClick={() => toggleCategory(group)}
                        aria-pressed={Boolean(categorySelected)}
                        className="flex items-center gap-3 rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                      >
                        <span
                          className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
                            categorySelected
                              ? 'bg-indigo-600 border-indigo-600'
                              : 'border-gray-300 hover:border-indigo-400'
                          }`}
                        >
                          {categorySelected && (
                            <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                          )}
                        </span>
                        <span className="block text-lg font-semibold text-gray-900">{group.name}</span>
                      </button>
                      <span className="text-sm text-gray-500">
                        {selectedCount > 0 ? `已选 ${selectedCount}/${totalCount}` : `${totalCount} 项`}
                      </span>
                    </div>
                  </div>

                  {/* 大类课点列表 */}
                  {categoryItems.length > 0 && (
                    <div className="p-4">
                      <div className="grid grid-cols-3 gap-4">
                        {categoryItems.map(({ course, item }) => {
                          const itemSelected = isItemSelected(course.id, item.id);
                          // 优先使用icon字段（具体图片文件），file字段是文件夹路径
                          const itemImage = item.icon || item.file || DEFAULT_ITEM_IMAGE;

                          return (
                            <button
                              key={`${course.id}:${item.id}`}
                              type="button"
                              onClick={() => toggleItem(course.id, item.id)}
                              aria-pressed={itemSelected}
                              aria-label={`${item.name}${itemSelected ? '，已选中' : ''}`}
                              className={`bg-gray-50 rounded-lg overflow-hidden border-2 transition-all hover:shadow-md ${
                                itemSelected
                                  ? 'border-indigo-500 ring-2 ring-indigo-200'
                                  : 'border-gray-200'
                              }`}
                            >
                              <div className="relative aspect-video overflow-hidden bg-gray-100">
                                <img
                                  src={getImageUrl(itemImage)}
                                  alt={item.name}
                                  className="w-full h-full object-cover"
                                  onError={(e) => {
                                    const image = e.currentTarget;
                                    image.onerror = null;
                                    image.src = DEFAULT_ITEM_IMAGE;
                                  }}
                                />
                                {itemSelected && (
                                  <span
                                    className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-indigo-600 text-white shadow-md"
                                    aria-hidden="true"
                                  >
                                    <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                    </svg>
                                  </span>
                                )}
                              </div>
                              <div className="p-3">
                                <h4 className="text-sm font-medium text-gray-900 text-center">{item.name}</h4>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-12">
            <p className="text-gray-500">该类别下暂无课程</p>
          </div>
        )}
        </div>
      </div>

      {/* 右下角固定按钮 */}
      <div className="fixed bottom-8 right-8">
        <button
          onClick={handleStart}
          disabled={getSelectedCount() === 0}
          className={`px-12 py-4 rounded-xl shadow-lg transition-all ${
            getSelectedCount() > 0
              ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          开始 ({getSelectedCount()})
        </button>
      </div>
    </div>
  );
}
