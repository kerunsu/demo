import path from "node:path";
import { readdirSync } from "node:fs";
import { runtimeConfig } from "../config/runtime.js";
import { completeSession, saveSession } from "./sessionLifecycleService.js";
import type { CourseQuestion, CourseType, Session } from "../types.js";

const cwd = process.cwd();
const projectRoot = path.basename(cwd).toLowerCase() === "backend" ? path.resolve(cwd, "..") : cwd;
const matchingDir = path.join(projectRoot, "matching");
const orderingDir = path.join(projectRoot, "paixu");

const MATCHING_RESOURCE_ERROR = "matching 图片资源不足，至少需要 4 张图片";
const MATCHING_PROMPT = "请点击和上面图片一样的图片";
const MATCHING_TARGET = "找到和上面一样的图片";
const MATCHING_HINT = "可以先看颜色和外轮廓，再找一模一样的图。";
const ORDERING_RESOURCE_ERROR = "paixu 图片资源不足，无法生成排序题目";
const ORDERING_PROMPT = "请根据规则选择正确的图片";
const ORDERING_HINT = "先比较两个图片，再按规则选择。";
const CORRECT_FEEDBACK = "回答正确，真棒！";
const WRONG_FEEDBACK = "这次不对，再试一下。";
const MATCHING_IMAGE_SEMANTICS: Record<string, { label: string; description: string }> = {
  "image_1.jpg": { label: "苹果", description: "一颗红色苹果，有黑色果柄和可爱的笑脸" },
  "image_2.jpg": { label: "桃子", description: "一个粉色桃子，下面有一片绿色叶子" },
  "image_3.jpg": { label: "香蕉", description: "一串黄色香蕉，有三根弯弯的香蕉" },
  "image_4.jpg": { label: "菠萝", description: "一个黄色菠萝，上面有绿色叶子，身上有格子纹" },
  "image_5.jpg": { label: "西瓜", description: "一个绿色西瓜，外面有深绿色条纹" },
  "image_6.jpg": { label: "草莓", description: "一颗红色草莓，上面有绿色叶子和黄色小点" },
  "image_7.jpg": { label: "葡萄", description: "一串紫色葡萄，上面有绿色叶子" },
  "057/001.jpg": { label: "小汽车", description: "一辆红色小汽车，有两个黑色轮子" },
  "058/001.jpg": { label: "篮球", description: "一个橙色篮球，上面有白色线条" },
  "059/001.jpg": { label: "绿色尖尖块", description: "一个绿色尖尖块" },
  "060/001.jpg": { label: "水杯", description: "一个蓝色水杯，杯子中间有白色感叹号" },
  "061/001.jpg": { label: "椅子", description: "一把橙色椅子，靠背中间有白色爱心图案" },
  "062/001.jpg": { label: "自行车", description: "一辆红色和灰色的小自行车" },
  "063/001.jpg": { label: "碗", description: "一个黄色的碗，里面是白色的" },
  "064/001.jpg": { label: "彩色球", description: "一个彩色球，有蓝色边线和彩色块" }
};

const ORDERING_RULES: Record<string, RuleSpec[]> = {
  BigSmall: [
    { text: "选更大的", selectHigher: true },
    { text: "选更小的", selectHigher: false }
  ],
  LongShort: [
    { text: "选更长的", selectHigher: true },
    { text: "选更短的", selectHigher: false }
  ],
  TallShort: [
    { text: "选更高的", selectHigher: true },
    { text: "选更矮的", selectHigher: false }
  ],
  MoreLess: [
    { text: "选更多的", selectHigher: true },
    { text: "选更少的", selectHigher: false }
  ]
};

function toPublicUrl(fileAbsolutePath: string) {
  const relative = path.relative(projectRoot, fileAbsolutePath).replace(/\\/g, "/");
  return `${runtimeConfig.publicBackendOrigin}/${relative}`;
}

function matchingSemantic(fileAbsolutePath: string) {
  const relative = path.relative(matchingDir, fileAbsolutePath).replace(/\\/g, "/");
  return MATCHING_IMAGE_SEMANTICS[relative] ?? {
    label: path.basename(fileAbsolutePath, path.extname(fileAbsolutePath)),
    description: "一张需要观察颜色、形状和图案的图片"
  };
}

function shuffle<T>(arr: T[]) {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function sampleMany<T>(arr: T[], count: number): T[] {
  return shuffle(arr).slice(0, Math.min(count, arr.length));
}

function safeReadDirFiles(dir: string) {
  try {
    return readdirSync(dir, { withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => path.join(dir, entry.name));
  } catch {
    return [];
  }
}

function getMatchingImages() {
  const directFiles = safeReadDirFiles(matchingDir).filter((file) => /\.(jpg|jpeg|png|webp)$/i.test(file));
  const nestedFiles: string[] = [];
  try {
    const dirs = readdirSync(matchingDir, { withFileTypes: true }).filter((entry) => entry.isDirectory());
    for (const dir of dirs) {
      const nested = safeReadDirFiles(path.join(matchingDir, dir.name)).filter((file) =>
        /\.(jpg|jpeg|png|webp)$/i.test(file)
      );
      nestedFiles.push(...nested);
    }
  } catch {
    // no-op
  }
  const all = [...directFiles, ...nestedFiles];
  return Array.from(new Set(all));
}

function buildMatchingQuestions(): CourseQuestion[] {
  const images = getMatchingImages();
  const usable = images.length >= 4 ? images : [];
  if (usable.length === 0) {
    throw new Error(MATCHING_RESOURCE_ERROR);
  }

  const targets = sampleMany(usable, Math.min(8, usable.length));
  return targets.map((targetImage, index) => {
    const distractors = sampleMany(
      usable.filter((item) => item !== targetImage),
      3
    );
    const options = shuffle([targetImage, ...distractors]).map((imgPath, optionIndex) => {
      const semantic = matchingSemantic(imgPath);
      return {
        id: `m_q${index + 1}_o${optionIndex + 1}`,
        label: semantic.label,
        description: semantic.description,
        imageUrl: toPublicUrl(imgPath)
      };
    });
    const correctOption = options.find((option) => option.imageUrl === toPublicUrl(targetImage));
    const targetSemantic = matchingSemantic(targetImage);
    return {
      id: `matching_q_${index + 1}`,
      prompt: MATCHING_PROMPT,
      target: targetSemantic.label,
      targetDescription: targetSemantic.description,
      targetImageUrl: toPublicUrl(targetImage),
      options,
      correctOptionId: correctOption?.id ?? options[0].id,
      hint: MATCHING_HINT,
      errorTypeOnWrong: "mismatch" as const
    };
  });
}

type RuleSpec = { text: string; selectHigher: boolean };

const MORE_LESS_ITEM_NAMES: Record<string, string> = {
  apple: "苹果",
  cookie: "饼干",
  cup: "杯子",
  pencil: "铅笔"
};

function orderingOptionDescription(category: string, prefix: string, level: number, index: number) {
  if (category === "MoreLess") {
    const side = index === 0 ? "左边" : index === 1 ? "右边" : `第${index + 1}张`;
    const itemName = MORE_LESS_ITEM_NAMES[prefix] ?? "东西";
    return `${side}这张有${level}个${itemName}`;
  }
  return undefined;
}

function parseOrderingGroup(categoryDir: string) {
  const files = safeReadDirFiles(categoryDir)
    .filter((file) => /\.(png|jpg|jpeg|webp)$/i.test(file))
    .filter((file) => !/background/i.test(path.basename(file)));
  const groups = new Map<string, Array<{ path: string; level: number }>>();

  for (const file of files) {
    const baseName = path.basename(file, path.extname(file));
    const levelMatch = baseName.match(/(\d+)$/);
    if (!levelMatch) continue;
    const level = Number(levelMatch[1]);
    const prefix = baseName.replace(/\d+$/, "");
    const arr = groups.get(prefix) ?? [];
    arr.push({ path: file, level });
    groups.set(prefix, arr);
  }

  for (const [prefix, arr] of groups) {
    groups.set(
      prefix,
      arr.sort((a, b) => a.level - b.level)
    );
  }
  return groups;
}

function buildOrderingQuestions(): CourseQuestion[] {
  const questions: CourseQuestion[] = [];
  for (const [category, rules] of Object.entries(ORDERING_RULES)) {
    const categoryDir = path.join(orderingDir, category);
    const groups = parseOrderingGroup(categoryDir);
    for (const [prefix, items] of groups) {
      if (items.length < 2) continue;
      const chosen = sampleMany(items, 2);
      const rule = rules[Math.floor(Math.random() * rules.length)];
      const sorted = [...chosen].sort((a, b) => a.level - b.level);
      const correctItem = rule.selectHigher ? sorted[sorted.length - 1] : sorted[0];
      const options = shuffle(chosen).map((item, index) => ({
        id: `o_${category}_${prefix}_${index + 1}_${item.level}`,
        label: `选项 ${index + 1}`,
        description: orderingOptionDescription(category, prefix, item.level, index),
        imageUrl: toPublicUrl(item.path),
        level: item.level
      }));
      const correct = options.find((option) => option.level === correctItem.level);
      questions.push({
        id: `ordering_${category}_${prefix}_${questions.length + 1}`,
        prompt: ORDERING_PROMPT,
        target: rule.text,
        options,
        correctOptionId: correct?.id ?? options[0].id,
        hint: ORDERING_HINT,
        errorTypeOnWrong: "wrong_order"
      });
    }
  }

  if (questions.length === 0) {
    throw new Error(ORDERING_RESOURCE_ERROR);
  }
  return sampleMany(questions, Math.min(12, questions.length));
}

export function buildCourseQuestions(courseType: CourseType): CourseQuestion[] {
  return courseType === "matching" ? buildMatchingQuestions() : buildOrderingQuestions();
}

export function getCurrentQuestionSnapshot(session: Session) {
  const questions = session.questions;
  const question = questions[session.currentQuestionIndex];
  if (!question) {
    throw new Error("Question not found");
  }

  return {
    questionId: question.id,
    courseType: session.courseType,
    index: session.currentQuestionIndex + 1,
    total: questions.length,
    prompt: question.prompt,
    payload: {
      target: question.target,
      targetDescription: question.targetDescription,
      targetImageUrl: question.targetImageUrl,
      options: question.options,
      correctOptionId: question.correctOptionId
    }
  };
}

export function submitCourseAnswer(
  session: Session,
  questionId: string,
  selectedOptionId: string,
  responseTimeMs: number
) {
  const questions = session.questions;
  const question = questions[session.currentQuestionIndex];
  if (!question || question.id !== questionId) {
    throw new Error("Question does not match current session progress");
  }

  const stat = session.questionStats[session.currentQuestionIndex];
  stat.attempts += 1;

  const isCorrect = selectedOptionId === question.correctOptionId;
  if (isCorrect) {
    stat.correct = true;
    stat.responseTimeMs = responseTimeMs;
    session.correctAnswers += 1;
    session.responseTimes.push(responseTimeMs);
    session.currentQuestionIndex += 1;
  } else {
    session.totalWrongAttempts += 1;
    stat.wrongTypes.push(question.errorTypeOnWrong);
  }

  const courseCompleted = session.currentQuestionIndex >= questions.length;
  if (courseCompleted) {
    completeSession(session);
  } else {
    saveSession(session);
  }

  const hint = !isCorrect && stat.attempts >= 2 ? question.hint : null;
  return {
    correct: isCorrect,
    feedback: isCorrect ? CORRECT_FEEDBACK : WRONG_FEEDBACK,
    hint,
    correctOptionId: question.correctOptionId,
    nextAction: isCorrect ? "NEXT_QUESTION" : "RETRY_SAME_QUESTION",
    courseCompleted
  } as const;
}
