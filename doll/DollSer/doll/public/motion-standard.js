(function initMotionStandard(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MotionStandard = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createMotionStandard() {
  'use strict';

  const FORMAT = 'dollser-motion';
  const VERSION = 2;
  const PUBLIC_AXES = ['pitch', 'yaw', 'armL', 'armR'];
  const PHASES = ['move', 'return'];

  function issue(severity, code, path, message) {
    return { severity, code, path, message };
  }

  function isFiniteNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function buildSequenceExpressionTiming(expression = {}, motionDurationMs = 0) {
    const hasExpression = typeof expression.mediaId === 'string' && expression.mediaId.trim();
    const rawOffset = Number(expression.offsetMs);
    const offsetMs = hasExpression && Number.isFinite(rawOffset)
      ? Math.min(30000, Math.max(-30000, Math.round(rawOffset)))
      : 0;
    const rawExpressionDuration = Number(expression.durationMs);
    const expressionDurationMs = Number.isFinite(rawExpressionDuration)
      ? Math.min(30000, Math.max(100, Math.round(rawExpressionDuration)))
      : 1000;
    const safeMotionDurationMs = Number.isFinite(Number(motionDurationMs))
      ? Math.max(0, Math.round(Number(motionDurationMs)))
      : 0;
    const motionStartTime = Math.max(0, -offsetMs);
    const expressionTime = hasExpression ? motionStartTime + offsetMs : 0;
    const durationMs = Math.max(
      motionStartTime + safeMotionDurationMs,
      hasExpression ? expressionTime + expressionDurationMs : 0
    );
    return { offsetMs, motionStartTime, expressionTime, expressionDurationMs, durationMs };
  }

  function validateMotionDocument(document) {
    const issues = [];
    const value = document && typeof document === 'object' && !Array.isArray(document) ? document : {};
    const commands = Array.isArray(value.commands) ? value.commands : [];
    const expressions = value.expression && typeof value.expression === 'object'
      ? [value.expression]
      : (Array.isArray(value.expressions) ? value.expressions : []);

    if (value.format !== FORMAT) {
      issues.push(issue('error', 'format', 'format', `format 必须是 ${FORMAT}`));
    }
    if (value.version !== VERSION) {
      issues.push(issue('error', 'version', 'version', `version 必须是 ${VERSION}`));
    }
    if (typeof value.name !== 'string' || !value.name.trim()) {
      issues.push(issue('error', 'name', 'name', '动作名称不能为空'));
    }
    if (!isFiniteNumber(value.durationMs) || value.durationMs < 0) {
      issues.push(issue('error', 'duration', 'durationMs', 'durationMs 必须是大于等于 0 的数字'));
    }
    if (!value.initialPose || typeof value.initialPose !== 'object') {
      issues.push(issue('error', 'initial-pose', 'initialPose', 'initialPose 不能为空'));
    } else {
      PUBLIC_AXES.forEach((axis) => {
        const angle = value.initialPose[axis];
        if (!isFiniteNumber(angle) || angle < 0 || angle > 359) {
          issues.push(issue('error', 'initial-angle', `initialPose.${axis}`, '初始角度必须在 0..359 之间'));
        }
      });
    }
    if (!Array.isArray(value.commands) || commands.length === 0) {
      issues.push(issue('error', 'commands', 'commands', 'commands 至少需要一条指令'));
    }
    if (value.armBaselineVersion === undefined) {
      issues.push(issue('warning', 'arm-baseline', 'armBaselineVersion', '未声明手臂基准版本，导入方会按旧版数据迁移'));
    } else if (value.armBaselineVersion !== VERSION) {
      issues.push(issue('warning', 'arm-baseline', 'armBaselineVersion', `建议使用手臂基准版本 ${VERSION}`));
    }

    let latestEndMs = 0;
    let previousTime = -1;
    const axisBusyUntil = {};
    commands.forEach((command, index) => {
      const path = `commands[${index}]`;
      if (!command || typeof command !== 'object' || Array.isArray(command)) {
        issues.push(issue('error', 'command', path, '指令必须是对象'));
        return;
      }
      if (!isFiniteNumber(command.time) || command.time < 0) {
        issues.push(issue('error', 'command-time', `${path}.time`, 'time 必须是大于等于 0 的数字'));
      }
      if (!PUBLIC_AXES.includes(command.axis)) {
        issues.push(issue('error', 'command-axis', `${path}.axis`, `axis 必须是 ${PUBLIC_AXES.join(' / ')}`));
      }
      if (!isFiniteNumber(command.angle) || command.angle < 0 || command.angle > 359) {
        issues.push(issue('error', 'command-angle', `${path}.angle`, 'angle 必须在 0..359 之间'));
      }
      if (!isFiniteNumber(command.moveMs) || command.moveMs < 50 || command.moveMs > 5000) {
        issues.push(issue('error', 'command-move', `${path}.moveMs`, 'moveMs 必须在 50..5000 之间'));
      }
      if (!command.actionId || typeof command.actionId !== 'string') {
        issues.push(issue('warning', 'action-id', `${path}.actionId`, '建议填写 actionId，便于导入时配对回中指令'));
      }
      if (!command.label || typeof command.label !== 'string') {
        issues.push(issue('warning', 'label', `${path}.label`, '建议填写 label，便于测试与交接'));
      }
      if (command.phase !== undefined && !PHASES.includes(command.phase)) {
        issues.push(issue('warning', 'phase', `${path}.phase`, 'phase 建议使用 move 或 return'));
      }

      if (isFiniteNumber(command.time)) {
        if (command.time < previousTime) {
          issues.push(issue('warning', 'order', path, '指令未按 time 升序排列'));
        }
        previousTime = command.time;
      }
      if (PUBLIC_AXES.includes(command.axis) && isFiniteNumber(command.time) && isFiniteNumber(command.moveMs)) {
        if (command.time < (axisBusyUntil[command.axis] || 0)) {
          issues.push(issue('warning', 'axis-overlap', path, `${command.axis} 的上一条指令尚未完成，本指令会提前接管该轴`));
        }
        axisBusyUntil[command.axis] = command.time + command.moveMs;
        latestEndMs = Math.max(latestEndMs, axisBusyUntil[command.axis]);
      }
    });

    const actionIds = new Set(commands.map((command) => command?.actionId).filter(Boolean));
    expressions.forEach((expression, index) => {
      const path = value.expression ? 'expression' : `expressions[${index}]`;
      if (!expression || typeof expression !== 'object' || Array.isArray(expression)) {
        issues.push(issue('error', 'expression', path, '表情提示必须是对象'));
        return;
      }
      const isSequenceExpression = expression.scope === 'sequence' || Boolean(value.expression);
      if (!isSequenceExpression && (!expression.actionId || !actionIds.has(expression.actionId))) {
        issues.push(issue('warning', 'expression-action', `${path}.actionId`, '表情提示没有匹配到动作指令'));
      }
      if (typeof expression.mediaId !== 'string' || !expression.mediaId.trim()) {
        issues.push(issue('error', 'expression-media', `${path}.mediaId`, 'mediaId 不能为空'));
      }
      if (!isFiniteNumber(expression.time) || expression.time < 0) {
        issues.push(issue('error', 'expression-time', `${path}.time`, '表情开始时间必须大于等于 0'));
      }
      if (!isFiniteNumber(expression.durationMs) || expression.durationMs < 100 || expression.durationMs > 30000) {
        issues.push(issue('error', 'expression-duration', `${path}.durationMs`, '表情显示时长必须在 100..30000 之间'));
      }
      if (expression.offsetMs !== undefined && !isFiniteNumber(expression.offsetMs)) {
        issues.push(issue('error', 'expression-offset', `${path}.offsetMs`, 'offsetMs 必须是数字，负数表示表情提前'));
      }
      const referenceTime = expression.motionStartTime ?? expression.actionTime;
      if (
        isFiniteNumber(expression.time)
        && isFiniteNumber(referenceTime)
        && isFiniteNumber(expression.offsetMs)
        && Math.abs((expression.time - referenceTime) - expression.offsetMs) > 1
      ) {
        issues.push(issue('warning', 'expression-offset-mismatch', path, 'time、动作序列开始时间与 offsetMs 不一致'));
      }
      if (isFiniteNumber(expression.time) && isFiniteNumber(expression.durationMs)) {
        latestEndMs = Math.max(latestEndMs, expression.time + expression.durationMs);
      }
    });

    if (isFiniteNumber(value.durationMs) && value.durationMs < latestEndMs) {
      issues.push(issue('error', 'duration-cover', 'durationMs', `总时长必须覆盖最后一条指令（至少 ${latestEndMs} ms）`));
    }

    const errors = issues.filter((item) => item.severity === 'error');
    const warnings = issues.filter((item) => item.severity === 'warning');
    return {
      valid: errors.length === 0,
      issues,
      errors,
      warnings,
      stats: {
        commandCount: commands.length,
        durationMs: isFiniteNumber(value.durationMs) ? value.durationMs : 0,
        axisCount: new Set(commands.map((command) => command && command.axis).filter((axis) => PUBLIC_AXES.includes(axis))).size,
        latestEndMs,
        expressionCount: expressions.length,
      },
    };
  }

  function formatIssue(item) {
    return `${item.path}: ${item.message}`;
  }

  return { FORMAT, VERSION, PUBLIC_AXES, buildSequenceExpressionTiming, validateMotionDocument, formatIssue };
}));
