import { useEffect, useRef, useState } from "react";
import { findRobotAnimationById, ROBOT_ANIMATION_MANIFEST } from "child-education-training-demo/shared/animations";
import { resolveBackendAssetUrl } from "../../config/runtime";

type StageState = {
  layerA: string | null;
  layerB: string | null;
  showA: boolean;
};

type RobotGifStageProps = {
  src: string | null;
  onError: () => void;
};

const FEEDBACK_ANIMATION_IDS = ["happy", "curious", "excited"] as const;

export function RobotGifStage({ src, onError }: RobotGifStageProps) {
  const [stage, setStage] = useState<StageState>({ layerA: null, layerB: null, showA: true });
  const displayedSrcRef = useRef<string | null>(null);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  useEffect(() => {
    for (const animationId of FEEDBACK_ANIMATION_IDS) {
      const manifest = findRobotAnimationById(animationId);
      const preload = new Image();
      preload.src = resolveBackendAssetUrl(manifest.resourceRef);
    }
    const idleManifest = ROBOT_ANIMATION_MANIFEST.find((item) => item.animationId === "eye");
    if (idleManifest) {
      const preload = new Image();
      preload.src = resolveBackendAssetUrl(idleManifest.resourceRef);
    }
  }, []);

  useEffect(() => {
    if (!src || src === displayedSrcRef.current) return;

    let cancelled = false;
    const loader = new Image();
    loader.onload = () => {
      if (cancelled) return;
      setStage((prev) => {
        if (prev.showA) {
          return { layerA: prev.layerA, layerB: src, showA: false };
        }
        return { layerA: src, layerB: prev.layerB, showA: true };
      });
      displayedSrcRef.current = src;
    };
    loader.onerror = () => {
      if (!cancelled) onErrorRef.current();
    };
    loader.src = src;

    return () => {
      cancelled = true;
    };
  }, [src]);

  const hasImage = stage.layerA !== null || stage.layerB !== null;

  return (
    <div className="robot-gif-stage">
      {stage.layerA ? (
        <img
          className={`robot-gif robot-gif-fullscreen robot-gif-layer${stage.showA ? " is-active" : ""}`}
          src={stage.layerA}
          alt="机器人表情动画"
          draggable={false}
        />
      ) : null}
      {stage.layerB ? (
        <img
          className={`robot-gif robot-gif-fullscreen robot-gif-layer${stage.showA ? "" : " is-active"}`}
          src={stage.layerB}
          alt=""
          aria-hidden={stage.showA}
          draggable={false}
        />
      ) : null}
      {!hasImage ? (
        <div className="robot-face-shell robot-face-shell-fullscreen" aria-hidden="true">
          <div className="robot-face-eye left" />
          <div className="robot-face-eye right" />
          <div className="robot-face-mouth" />
        </div>
      ) : null}
    </div>
  );
}
