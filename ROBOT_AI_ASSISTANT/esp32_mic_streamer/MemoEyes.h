#ifndef MEMO_EYES_H
#define MEMO_EYES_H

#include <Arduino.h>
#include <U8g2lib.h>
#include <math.h>

/**
 * ============================================================================
 *  MEMO AI Robot — Procedural Vector-Style Eye Engine
 * ============================================================================
 *  Inspired by Anki Vector & Cozmo.
 *  Uses classical Pixar animation principles:
 *    - Squash & Stretch interpolation
 *    - Saccades (unconscious biological micro-darts)
 *    - Anticipation & Snappy Easing
 *    - Asymmetric expressions (e.g. curious raised eyebrow)
 *    - Smooth autonomic blinking with double-blink probability
 *    - Hardware tilt / Gyro tracking support
 *
 *  Designed for SSD1306 / SH1106 128x64 OLED displays running on U8g2.
 * ============================================================================
 */

enum EyeEmotion {
  EMOTION_NEUTRAL,    // Vector resting state: calm rounded rectangular capsules
  EMOTION_HAPPY,      // Pixar smile: lower eyelids curve up into crescent arcs
  EMOTION_ANGRY,      // Furrowed brow: top eyelids slice sharply downward inward (\ /)
  EMOTION_SAD,        // Drooping / worried: top eyelids slope downward outward (/ \)
  EMOTION_SLEEPY,     // Heavy upper eyelid droop (- -), slow relaxed blinks
  EMOTION_CURIOUS,    // Asymmetric: one eye raised high & wide, other squinted
  EMOTION_SURPRISED,  // Wide, tall elongated eyes (pop out)
  EMOTION_THINKING,   // Glancing up-right with gentle pulse / scan
  EMOTION_LISTENING,  // Attentive wide eyes, subtle listening pulse
  EMOTION_SPEAKING,   // Rhythmic speech bounce/squash with animated mouth
  EMOTION_DIZZY,      // Knocked over / shaken: rotating crosses or spiral
  EMOTION_HEARTS      // Vector in love: animated heart eyes (<3 <3)
};

enum BlinkState {
  BLINK_IDLE,
  BLINK_CLOSING,
  BLINK_CLOSED,
  BLINK_OPENING,
  BLINK_OVERSHOOT
};

struct EyeGeometry {
  float x;              // Center X (screen pixels)
  float y;              // Center Y (screen pixels)
  float width;          // Box width
  float height;         // Box height
  float radius;         // Corner radius
  float topLid;         // Horizontal top lid droop (pixels from top)
  float bottomLidFlat;  // Horizontal bottom lid cut (pixels from bottom)
  float bottomLidCurve; // Curved smile cut depth (pixels rising from bottom)
  float topLidAngle;    // Slanted brow (pixels: >0 inward/angry, <0 outward/sad)
};

class MemoEyes {
private:
  // Display reference constants
  static const int16_t SCREEN_W = 128;
  static const int16_t SCREEN_H = 64;

  // Eye Neutral Rest Centers
  const float DEFAULT_LEFT_X  = 44.0f;
  const float DEFAULT_RIGHT_X = 84.0f;
  const float DEFAULT_Y       = 32.0f;

  // Current animated geometries (smoothly moving)
  EyeGeometry leftEye;
  EyeGeometry rightEye;

  // Target geometries for current emotion
  EyeGeometry targetLeft;
  EyeGeometry targetRight;

  // Active Emotion & State
  EyeEmotion currentEmotion = EMOTION_NEUTRAL;
  EyeEmotion previousEmotion = EMOTION_NEUTRAL;

  // Gaze Offset (from joystick, head tracking, or MPU6050 gyro)
  float gazeTargetX = 0.0f;
  float gazeTargetY = 0.0f;
  float gazeCurrentX = 0.0f;
  float gazeCurrentY = 0.0f;

  // Autonomic behaviors (Saccades & Blinking)
  bool autonomicEnabled = true;
  unsigned long nextBlinkTime = 0;
  unsigned long nextSaccadeTime = 0;
  float saccadeOffsetX = 0.0f;
  float saccadeOffsetY = 0.0f;

  // Blinking State Machine
  BlinkState blinkState = BLINK_IDLE;
  unsigned long blinkTimer = 0;
  float blinkProgress = 0.0f; // 0.0 = fully open, 1.0 = fully closed
  bool isDoubleBlink = false;

  // Speaking & Mouth Animation
  bool showMouth = true;
  float mouthOpen = 0.0f;
  float mouthTarget = 0.0f;

  // Audio Reactivity
  uint16_t audioLevel = 0;

  // Frame timing
  unsigned long lastUpdateTime = 0;
  float animationPhase = 0.0f;

  // Easing helper
  static inline float lerp(float a, float b, float t) {
    return a + (b - a) * t;
  }

  static inline float clamp(float v, float minVal, float maxVal) {
    if (v < minVal) return minVal;
    if (v > maxVal) return maxVal;
    return v;
  }

public:
  MemoEyes() {
    initNeutralGeometry(leftEye, DEFAULT_LEFT_X, DEFAULT_Y);
    initNeutralGeometry(rightEye, DEFAULT_RIGHT_X, DEFAULT_Y);
    targetLeft = leftEye;
    targetRight = rightEye;
  }

  void begin() {
    unsigned long now = millis();
    nextBlinkTime = now + random(2500, 5000);
    nextSaccadeTime = now + random(1500, 3500);
    lastUpdateTime = now;
  }

  void initNeutralGeometry(EyeGeometry &g, float x, float y) {
    g.x = x;
    g.y = y;
    g.width = 30.0f;
    g.height = 36.0f;
    g.radius = 8.0f;
    g.topLid = 0.0f;
    g.bottomLidFlat = 0.0f;
    g.bottomLidCurve = 0.0f;
    g.topLidAngle = 0.0f;
  }

  // ── EMOTION SELECTOR ───────────────────────────────────────────────────────
  void setEmotion(EyeEmotion emotion) {
    if (currentEmotion == emotion && emotion != EMOTION_SPEAKING) return;
    previousEmotion = currentEmotion;
    currentEmotion = emotion;

    switch (emotion) {
      case EMOTION_NEUTRAL:
        initNeutralGeometry(targetLeft, DEFAULT_LEFT_X, DEFAULT_Y);
        initNeutralGeometry(targetRight, DEFAULT_RIGHT_X, DEFAULT_Y);
        break;

      case EMOTION_HAPPY:
        // Cheerful Pixar smile: eyes raise slightly, lower eyelid cuts into upward arc
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y - 4.0f;
        targetRight.y = DEFAULT_Y - 4.0f;
        targetLeft.width = 32.0f;
        targetRight.width = 32.0f;
        targetLeft.height = 34.0f;
        targetRight.height = 34.0f;
        targetLeft.radius = 8.0f;
        targetRight.radius = 8.0f;
        targetLeft.topLid = 2.0f;
        targetRight.topLid = 2.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 0.0f;
        targetRight.bottomLidFlat = 0.0f;
        targetLeft.bottomLidCurve = 16.0f;  // Upward crescent smile
        targetRight.bottomLidCurve = 16.0f;
        break;

      case EMOTION_ANGRY:
        // Furrowed brow: eyes move slightly closer, sharp downward inward angle
        targetLeft.x = DEFAULT_LEFT_X + 3.0f;
        targetRight.x = DEFAULT_RIGHT_X - 3.0f;
        targetLeft.y = DEFAULT_Y + 2.0f;
        targetRight.y = DEFAULT_Y + 2.0f;
        targetLeft.width = 32.0f;
        targetRight.width = 32.0f;
        targetLeft.height = 30.0f;
        targetRight.height = 30.0f;
        targetLeft.radius = 6.0f;
        targetRight.radius = 6.0f;
        targetLeft.topLid = 3.0f;
        targetRight.topLid = 3.0f;
        targetLeft.topLidAngle = 14.0f;  // Sharp inward slant (\ /)
        targetRight.topLidAngle = 14.0f;
        targetLeft.bottomLidFlat = 2.0f;
        targetRight.bottomLidFlat = 2.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_SAD:
        // Drooping / worried: eyes droop down, top eyelids slope outward
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y + 4.0f;
        targetRight.y = DEFAULT_Y + 4.0f;
        targetLeft.width = 28.0f;
        targetRight.width = 28.0f;
        targetLeft.height = 32.0f;
        targetRight.height = 32.0f;
        targetLeft.radius = 7.0f;
        targetRight.radius = 7.0f;
        targetLeft.topLid = 4.0f;
        targetRight.topLid = 4.0f;
        targetLeft.topLidAngle = -12.0f; // Outward droop (/ \)
        targetRight.topLidAngle = -12.0f;
        targetLeft.bottomLidFlat = 2.0f;
        targetRight.bottomLidFlat = 2.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_SLEEPY:
        // Tired / drowsy: heavy eyelids halfway down
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y + 3.0f;
        targetRight.y = DEFAULT_Y + 3.0f;
        targetLeft.width = 30.0f;
        targetRight.width = 30.0f;
        targetLeft.height = 28.0f;
        targetRight.height = 28.0f;
        targetLeft.radius = 7.0f;
        targetRight.radius = 7.0f;
        targetLeft.topLid = 16.0f;       // Heavy drooping lids
        targetRight.topLid = 16.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 4.0f;
        targetRight.bottomLidFlat = 4.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_CURIOUS:
        // Classic Vector asymmetric cocked-head look: Left wide & high, Right squinted
        targetLeft.x = DEFAULT_LEFT_X;
        targetLeft.y = DEFAULT_Y - 5.0f;
        targetLeft.width = 34.0f;
        targetLeft.height = 42.0f;
        targetLeft.radius = 9.0f;
        targetLeft.topLid = 0.0f;
        targetLeft.topLidAngle = -4.0f;
        targetLeft.bottomLidFlat = 0.0f;
        targetLeft.bottomLidCurve = 0.0f;

        targetRight.x = DEFAULT_RIGHT_X;
        targetRight.y = DEFAULT_Y + 4.0f;
        targetRight.width = 27.0f;
        targetRight.height = 24.0f;
        targetRight.radius = 6.0f;
        targetRight.topLid = 7.0f;
        targetRight.topLidAngle = 4.0f;
        targetRight.bottomLidFlat = 4.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_SURPRISED:
        // Wide tall elongated eyes
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y;
        targetRight.y = DEFAULT_Y;
        targetLeft.width = 34.0f;
        targetRight.width = 34.0f;
        targetLeft.height = 48.0f;
        targetRight.height = 48.0f;
        targetLeft.radius = 12.0f;
        targetRight.radius = 12.0f;
        targetLeft.topLid = 0.0f;
        targetRight.topLid = 0.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 0.0f;
        targetRight.bottomLidFlat = 0.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_THINKING:
        // Glancing up & right, slight squint
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y - 2.0f;
        targetRight.y = DEFAULT_Y - 2.0f;
        targetLeft.width = 28.0f;
        targetRight.width = 28.0f;
        targetLeft.height = 32.0f;
        targetRight.height = 32.0f;
        targetLeft.radius = 7.0f;
        targetRight.radius = 7.0f;
        targetLeft.topLid = 5.0f;
        targetRight.topLid = 5.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 2.0f;
        targetRight.bottomLidFlat = 2.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        look(10, -8); // Look up and right
        break;

      case EMOTION_LISTENING:
        // Attentive wide eyes, ready to receive audio
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y;
        targetRight.y = DEFAULT_Y;
        targetLeft.width = 32.0f;
        targetRight.width = 32.0f;
        targetLeft.height = 40.0f;
        targetRight.height = 40.0f;
        targetLeft.radius = 9.0f;
        targetRight.radius = 9.0f;
        targetLeft.topLid = 0.0f;
        targetRight.topLid = 0.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 0.0f;
        targetRight.bottomLidFlat = 0.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        look(0, 0);
        break;

      case EMOTION_SPEAKING:
        // Base speaking geometry (animated dynamically in update())
        targetLeft.x = DEFAULT_LEFT_X;
        targetRight.x = DEFAULT_RIGHT_X;
        targetLeft.y = DEFAULT_Y;
        targetRight.y = DEFAULT_Y;
        targetLeft.width = 31.0f;
        targetRight.width = 31.0f;
        targetLeft.height = 36.0f;
        targetRight.height = 36.0f;
        targetLeft.radius = 8.0f;
        targetRight.radius = 8.0f;
        targetLeft.topLid = 0.0f;
        targetRight.topLid = 0.0f;
        targetLeft.topLidAngle = 0.0f;
        targetRight.topLidAngle = 0.0f;
        targetLeft.bottomLidFlat = 0.0f;
        targetRight.bottomLidFlat = 0.0f;
        targetLeft.bottomLidCurve = 0.0f;
        targetRight.bottomLidCurve = 0.0f;
        break;

      case EMOTION_DIZZY:
      case EMOTION_HEARTS:
        // Handled by custom rendering paths
        break;
    }
  }

  EyeEmotion getEmotion() const {
    return currentEmotion;
  }

  // ── GAZE DIRECTION ─────────────────────────────────────────────────────────
  // xOffset: -16 (look left) to +16 (look right)
  // yOffset: -10 (look up) to +10 (look down)
  void look(int8_t xOffset, int8_t yOffset) {
    gazeTargetX = clamp((float)xOffset, -16.0f, 16.0f);
    gazeTargetY = clamp((float)yOffset, -10.0f, 10.0f);
  }

  void center() {
    look(0, 0);
  }

  // ── BLINK CONTROL ──────────────────────────────────────────────────────────
  void blink() {
    if (blinkState == BLINK_IDLE) {
      blinkState = BLINK_CLOSING;
      blinkTimer = millis();
      blinkProgress = 0.0f;
    }
  }

  void setAutonomic(bool enabled) {
    autonomicEnabled = enabled;
  }

  void setShowMouth(bool enabled) {
    showMouth = enabled;
  }

  void setAudioLevel(uint16_t level) {
    audioLevel = level;
  }

  // ── UPDATE PHYSICS & ANIMATION (Call every ~20ms in loop) ──────────────────
  void update() {
    unsigned long now = millis();
    float dt = (now - lastUpdateTime) / 1000.0f;
    if (dt <= 0.001f) dt = 0.02f;
    if (dt > 0.1f) dt = 0.1f;
    lastUpdateTime = now;

    animationPhase += dt * 4.0f; // Oscillation clock

    // 1. AUTONOMIC SACCADES (Micro-movements that make Vector feel alive)
    if (autonomicEnabled && currentEmotion != EMOTION_DIZZY && currentEmotion != EMOTION_THINKING) {
      if (now > nextSaccadeTime) {
        if (random(100) < 65) {
          // Subtle biological micro-darts
          saccadeOffsetX = (float)random(-3, 4);
          saccadeOffsetY = (float)random(-2, 3);
          nextSaccadeTime = now + random(1000, 2500);
        } else {
          // Occasional full glance
          saccadeOffsetX = (float)random(-12, 13);
          saccadeOffsetY = (float)random(-5, 6);
          nextSaccadeTime = now + random(800, 1600);
        }
      }
    } else {
      saccadeOffsetX = 0.0f;
      saccadeOffsetY = 0.0f;
    }

    // 2. AUTONOMIC BLINKING
    if (autonomicEnabled && blinkState == BLINK_IDLE) {
      if (now > nextBlinkTime) {
        blink();
        isDoubleBlink = (random(100) < 18); // 18% chance of rapid double-blink
        nextBlinkTime = now + random(2800, 6000);
      }
    }

    // 3. BLINK STATE MACHINE
    updateBlink(now);

    // 4. SPEAKING & LISTENING DYNAMIC BOUNCE
    if (currentEmotion == EMOTION_SPEAKING) {
      float speechPulse = sinf(animationPhase * 3.5f);
      targetLeft.height = 36.0f + speechPulse * 5.0f;
      targetRight.height = targetLeft.height;
      targetLeft.y = DEFAULT_Y - speechPulse * 2.0f;
      targetRight.y = targetLeft.y;
      mouthTarget = fabsf(speechPulse) * 10.0f;
    } else if (currentEmotion == EMOTION_LISTENING) {
      // Dynamic audio bounce directly reactive to human voice loudness!
      float voicePulse = clamp((float)audioLevel / 600.0f, 0.0f, 6.0f);
      targetLeft.height = 40.0f + voicePulse;
      targetRight.height = 40.0f + voicePulse;
      mouthTarget = 0.0f;
    } else if (currentEmotion == EMOTION_HAPPY) {
      mouthTarget = 4.0f; // Gentle smile
    } else {
      mouthTarget = 0.0f;
    }

    // Smoothly decay audioLevel each frame
    audioLevel = (uint16_t)(audioLevel * 0.80f);

    // 5. SMOOTH INTERPOLATION (Pixar Squash & Stretch Physics)
    float smoothFactor = 0.28f; // Fast, organic deceleration

    gazeCurrentX = lerp(gazeCurrentX, gazeTargetX + saccadeOffsetX, smoothFactor);
    gazeCurrentY = lerp(gazeCurrentY, gazeTargetY + saccadeOffsetY, smoothFactor);
    mouthOpen = lerp(mouthOpen, mouthTarget, 0.35f);

    interpolateEye(leftEye, targetLeft, smoothFactor);
    interpolateEye(rightEye, targetRight, smoothFactor);
  }

  void updateBlink(unsigned long now) {
    switch (blinkState) {
      case BLINK_CLOSING: {
        // Fast snap close (~50ms)
        unsigned long elapsed = now - blinkTimer;
        blinkProgress = clamp(elapsed / 50.0f, 0.0f, 1.0f);
        if (elapsed >= 50) {
          blinkState = BLINK_CLOSED;
          blinkTimer = now;
          blinkProgress = 1.0f;
        }
        break;
      }
      case BLINK_CLOSED: {
        // Hold shut briefly (~25ms)
        if (now - blinkTimer >= 25) {
          blinkState = BLINK_OPENING;
          blinkTimer = now;
        }
        break;
      }
      case BLINK_OPENING: {
        // Smooth ease-out opening (~90ms)
        unsigned long elapsed = now - blinkTimer;
        blinkProgress = 1.0f - clamp(elapsed / 90.0f, 0.0f, 1.0f);
        if (elapsed >= 90) {
          blinkState = BLINK_OVERSHOOT;
          blinkTimer = now;
          blinkProgress = 0.0f;
        }
        break;
      }
      case BLINK_OVERSHOOT: {
        // Subtle vertical bounce before settling (~35ms)
        if (now - blinkTimer >= 35) {
          blinkState = BLINK_IDLE;
          if (isDoubleBlink) {
            isDoubleBlink = false;
            nextBlinkTime = now + 120; // Trigger second blink immediately!
          }
        }
        break;
      }
      case BLINK_IDLE:
      default:
        blinkProgress = 0.0f;
        break;
    }
  }

  void interpolateEye(EyeGeometry &cur, const EyeGeometry &tar, float factor) {
    cur.x = lerp(cur.x, tar.x, factor);
    cur.y = lerp(cur.y, tar.y, factor);
    cur.width = lerp(cur.width, tar.width, factor);
    cur.height = lerp(cur.height, tar.height, factor);
    cur.radius = lerp(cur.radius, tar.radius, factor);
    cur.topLid = lerp(cur.topLid, tar.topLid, factor);
    cur.bottomLidFlat = lerp(cur.bottomLidFlat, tar.bottomLidFlat, factor);
    cur.bottomLidCurve = lerp(cur.bottomLidCurve, tar.bottomLidCurve, factor);
    cur.topLidAngle = lerp(cur.topLidAngle, tar.topLidAngle, factor);
  }

  // ── RENDER TO U8G2 DISPLAY BUFFER ──────────────────────────────────────────
  void render(U8G2 &u8g2) {
    if (currentEmotion == EMOTION_HEARTS) {
      renderHearts(u8g2);
      return;
    }

    if (currentEmotion == EMOTION_DIZZY) {
      renderDizzy(u8g2);
      return;
    }

    // Standard Vector-style procedural eyes
    drawSingleEye(u8g2, leftEye, true);
    drawSingleEye(u8g2, rightEye, false);

    // Optional cute animated mouth
    if (showMouth && (mouthOpen > 0.5f || currentEmotion == EMOTION_HAPPY)) {
      renderMouth(u8g2);
    }
  }

private:
  void drawSingleEye(U8G2 &u8g2, const EyeGeometry &g, bool isLeft) {
    // Apply gaze shift
    float cx = g.x + gazeCurrentX;
    float cy = g.y + gazeCurrentY;

    // Apply blink vertical squash
    float currentH = g.height;
    if (blinkProgress > 0.0f) {
      currentH = lerp(g.height, 2.0f, blinkProgress); // Squashes down to 2px slit
    } else if (blinkState == BLINK_OVERSHOOT) {
      currentH += 2.5f; // Bouncy overshoot
    }

    float currentW = g.width;
    float currentR = g.radius;

    // Constrain corner radius to not exceed half dimension
    if (currentR > currentW / 2.0f) currentR = currentW / 2.0f;
    if (currentR > currentH / 2.0f) currentR = currentH / 2.0f;
    if (currentR < 0.0f) currentR = 0.0f;

    int16_t boxX = (int16_t)roundf(cx - currentW / 2.0f);
    int16_t boxY = (int16_t)roundf(cy - currentH / 2.0f);
    int16_t boxW = (int16_t)roundf(currentW);
    int16_t boxH = (int16_t)roundf(currentH);

    if (boxW <= 0 || boxH <= 0) return;

    // 1. Draw base white glowing capsule
    u8g2.setDrawColor(1);
    u8g2.drawRBox(boxX, boxY, boxW, boxH, (int16_t)roundf(currentR));

    // If blinking shut, the 2px slit is enough
    if (blinkProgress > 0.85f) return;

    // 2. Black pixel cutouts for eyelids & expressions
    u8g2.setDrawColor(0);

    // A. Top lid droop (Sleepy / Calm)
    if (g.topLid > 0.5f) {
      int16_t cutH = (int16_t)roundf(g.topLid);
      u8g2.drawBox(boxX - 2, boxY - 2, boxW + 4, cutH + 2);
    }

    // B. Slanted top eyelid (Angry \ / vs Sad / \)
    if (fabsf(g.topLidAngle) > 0.5f) {
      int16_t angleDepth = (int16_t)roundf(fabsf(g.topLidAngle));
      if (g.topLidAngle > 0.0f) {
        // Angry: Inner corner cuts deeper
        if (isLeft) {
          // Left eye inner edge is right side (boxX + boxW)
          u8g2.drawTriangle(boxX - 2, boxY - 2,
                            boxX + boxW + 2, boxY - 2,
                            boxX + boxW + 2, boxY + angleDepth);
        } else {
          // Right eye inner edge is left side (boxX)
          u8g2.drawTriangle(boxX - 2, boxY - 2,
                            boxX + boxW + 2, boxY - 2,
                            boxX - 2, boxY + angleDepth);
        }
      } else {
        // Sad / Worried: Outer corner cuts deeper
        if (isLeft) {
          // Left eye outer edge is left side (boxX)
          u8g2.drawTriangle(boxX - 2, boxY - 2,
                            boxX + boxW + 2, boxY - 2,
                            boxX - 2, boxY + angleDepth);
        } else {
          // Right eye outer edge is right side (boxX + boxW)
          u8g2.drawTriangle(boxX - 2, boxY - 2,
                            boxX + boxW + 2, boxY - 2,
                            boxX + boxW + 2, boxY + angleDepth);
        }
      }
    }

    // C. Bottom lid flat cut
    if (g.bottomLidFlat > 0.5f) {
      int16_t cutH = (int16_t)roundf(g.bottomLidFlat);
      u8g2.drawBox(boxX - 2, boxY + boxH - cutH, boxW + 4, cutH + 2);
    }

    // D. Bottom lid curved smile cutout (^ ^)
    if (g.bottomLidCurve > 0.5f) {
      int16_t discRadius = 26;
      int16_t discCenterY = boxY + boxH + discRadius - (int16_t)roundf(g.bottomLidCurve);
      u8g2.drawDisc((int16_t)roundf(cx), discCenterY, discRadius);
    }

    // Reset draw color back to white
    u8g2.setDrawColor(1);
  }

  void renderHearts(U8G2 &u8g2) {
    u8g2.setDrawColor(1);

    // Subtle heart pulse
    float pulse = sinf(animationPhase * 2.5f) * 1.5f;

    drawHeart(u8g2, DEFAULT_LEFT_X + gazeCurrentX, DEFAULT_Y + gazeCurrentY, 11.0f + pulse);
    drawHeart(u8g2, DEFAULT_RIGHT_X + gazeCurrentX, DEFAULT_Y + gazeCurrentY, 11.0f + pulse);
  }

  void drawHeart(U8G2 &u8g2, float cx, float cy, float r) {
    int16_t icx = (int16_t)roundf(cx);
    int16_t icy = (int16_t)roundf(cy);
    int16_t ir  = (int16_t)roundf(r);
    int16_t lobeR = (int16_t)roundf(ir * 0.60f);

    // Two top lobes
    u8g2.drawDisc(icx - lobeR + 1, icy - 3, lobeR);
    u8g2.drawDisc(icx + lobeR - 1, icy - 3, lobeR);

    // Downward tapering body
    u8g2.drawTriangle(icx - (int16_t)(ir * 1.15f), icy - 2,
                      icx + (int16_t)(ir * 1.15f), icy - 2,
                      icx, icy + (int16_t)(ir * 1.25f));
  }

  void renderDizzy(U8G2 &u8g2) {
    u8g2.setDrawColor(1);

    // Two spinning crosses / spiral stars
    float angle = animationPhase * 3.0f;
    float cosA = cosf(angle);
    float sinA = sinf(angle);
    float armLen = 14.0f;

    drawCross(u8g2, DEFAULT_LEFT_X, DEFAULT_Y, cosA, sinA, armLen);
    drawCross(u8g2, DEFAULT_RIGHT_X, DEFAULT_Y, cosA, sinA, armLen);
  }

  void drawCross(U8G2 &u8g2, float cx, float cy, float cosA, float sinA, float len) {
    int16_t x0 = (int16_t)roundf(cx - len * cosA);
    int16_t y0 = (int16_t)roundf(cy - len * sinA);
    int16_t x1 = (int16_t)roundf(cx + len * cosA);
    int16_t y1 = (int16_t)roundf(cy + len * sinA);

    int16_t x2 = (int16_t)roundf(cx + len * sinA);
    int16_t y2 = (int16_t)roundf(cy - len * cosA);
    int16_t x3 = (int16_t)roundf(cx - len * sinA);
    int16_t y3 = (int16_t)roundf(cy + len * cosA);

    // Thick lines for cross
    u8g2.drawLine(x0, y0, x1, y1);
    u8g2.drawLine(x0, y0 + 1, x1, y1 + 1);
    u8g2.drawLine(x0 + 1, y0, x1 + 1, y1);

    u8g2.drawLine(x2, y2, x3, y3);
    u8g2.drawLine(x2, y2 + 1, x3, y3 + 1);
    u8g2.drawLine(x2 + 1, y2, x3 + 1, y3);
  }

  void renderMouth(U8G2 &u8g2) {
    int16_t mouthCenterX = (int16_t)roundf((DEFAULT_LEFT_X + DEFAULT_RIGHT_X) / 2.0f + gazeCurrentX * 0.5f);
    int16_t mouthY = 56;
    int16_t mouthW = 14;
    int16_t mouthH = (int16_t)roundf(mouthOpen);

    u8g2.setDrawColor(1);
    if (mouthH <= 1) {
      // Resting little mouth line
      u8g2.drawLine(mouthCenterX - mouthW / 2, mouthY, mouthCenterX + mouthW / 2, mouthY);
    } else {
      // Open speech mouth box
      u8g2.drawRBox(mouthCenterX - mouthW / 2, mouthY - mouthH / 2, mouthW, mouthH, 2);
    }
  }
};

#endif // MEMO_EYES_H
