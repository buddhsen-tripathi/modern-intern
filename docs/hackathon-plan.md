# Gemini 3 Hackathon: Detailed Build Plans

---

# CONCEPT 1: "Kindness Speedrun"

## One-liner
A timed social game where AI watches your real-world interactions, scores your kindness, narrates your journey like a nature documentary, and adapts the background music to your social energy — all displayed on smart glasses.

---

## Core Game Loop

```
START (10-min timer begins)
  │
  ├─► IDLE STATE: Standing alone / on phone
  │     → Music: minor key, slow, ambient
  │     → Narrator: teases player ("The alchemist hesitates...")
  │     → Essence: slowly drains (-1/10sec)
  │     → Glasses HUD: "Seek connection..." prompt
  │
  ├─► SOCIAL ACTION DETECTED
  │     → Gemini classifies action + assigns points
  │     → Narrator: celebrates ("A bold approach!")
  │     → Music: key change, tempo up, brighter
  │     → Glasses HUD: "+20 Essence ✦ Streak: 3"
  │     → Essence bar fills
  │
  ├─► STREAK MECHANIC
  │     → 3+ actions without idle → "ON FIRE" multiplier (2×)
  │     → 5+ → "LEGENDARY" (3×)
  │     → Any idle break resets streak to 0
  │
  └─► TIMER HITS 0
        → Final score tallied
        → Rank assigned: Bronze / Silver / Gold / Platinum
        → Narrator delivers closing monologue
        → Music: triumphant fanfare or somber outro
```

---

## Scoring System

### Positive Actions (Essence Gained)
| Action | Points | How Gemini Detects It |
|---|---|---|
| Approach a stranger | +10 | Camera sees player moving toward a person, audio picks up greeting |
| Introduction (exchange names) | +15 | Audio detects "I'm [name]" / "my name is" patterns |
| Make someone laugh | +25 | Audio detects laughter from another person |
| Give a compliment | +15 | Audio sentiment analysis on player's speech |
| Help someone | +20 | Contextual — Gemini interprets collaborative body language + dialogue |
| High five / handshake | +15 | Camera detects hand-contact gesture between two people |
| Share food/drink | +20 | Camera sees object exchange near food area |
| Group conversation (3+) | +30 | Camera detects player in a cluster of 3+ people, audio confirms multi-party dialogue |
| Teach someone something | +25 | Audio detects explanatory speech patterns + questions from listener |

### Negative Actions (Essence Drained)
| Action | Penalty | Detection |
|---|---|---|
| Standing alone idle | -1/10sec | Camera: isolated figure, no social proximity |
| Phone staring | -2/10sec | Camera: head down posture, no speech |
| Walking away mid-conversation | -15 | Audio cuts off during active dialogue + camera shows movement away |
| Ignoring someone talking to you | -20 | Audio detects someone addressing player with no response for 10+ sec |
| Prolonged silence in a group | -10 | Camera shows group proximity but player audio is absent for 30+ sec |

### Streak Multipliers
- 0-2 consecutive actions: 1× multiplier
- 3-4 consecutive: 2× ("On Fire 🔥" shown on glasses)
- 5+: 3× ("LEGENDARY ⚡" shown on glasses)
- Idle for >20 seconds: streak resets

### Rank Thresholds (for 10-min game)
- **Bronze:** 200 essence
- **Silver:** 400 essence
- **Gold:** 700 essence
- **Platinum:** 1000+ essence

For the 3-min demo version, scale these down by ~3×.

---

## Glasses HUD Designs

### Main Game HUD (default view, text-based)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⏱ 7:23        ✦✦✦ STREAK: 3
  ESSENCE ████████░░░░ 340/700
  ► "Seek the ones who gather"
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Action Scored (flashes for 3 sec)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ★ LAUGHTER DETECTED ★
         +25 Essence
       Streak: 4 (2× ON FIRE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Idle Warning (after 15 sec idle)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ▼ ESSENCE FADING ▼
    The artifact grows cold...
    -1 every 10 sec
    ► Move. Connect. Act.
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Game Over Screen
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ═══ TIME'S UP ═══
    Final Essence: 482
    Rank: ★★ SILVER ★★
    Peak Streak: 5 (LEGENDARY)
    Social Actions: 14
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Narration System

### Gemini System Prompt (core)
```
You are the narrator of "Kindness Speedrun," a social adventure game.
You narrate the player's real-world social interactions in the style of
David Attenborough narrating a nature documentary — warm, witty,
observational, gently teasing when the player is idle, and genuinely
celebratory when they connect with others.

You receive a continuous stream of video (1 FPS) from the player's
phone camera and audio from their glasses microphone.

Your responsibilities:
1. DETECT social actions (greetings, laughter, compliments, helping,
   group formation, physical gestures like handshakes/high-fives)
2. CLASSIFY each action and call score_action() with the type and points
3. NARRATE what's happening in 1-2 sentences (spoken aloud via voice)
4. DETECT antisocial behavior (isolation, phone staring, ignoring others)
   and call penalize_action() accordingly
5. ADJUST music mood by calling update_music() with parameters
6. Keep narration SHORT (under 10 seconds per beat) so it doesn't
   talk over real conversations

Narration style examples:
- Player approaches someone: "Our intrepid alchemist spots a fellow
  human near the eastern waters. The approach begins..."
- Laughter detected: "And there it is — genuine laughter. The rarest
  of social currencies. The artifact hums with power."
- Player idle: "Minutes pass. The alchemist contemplates the void.
  The artifact... does not approve."
- Streak building: "Three connections in rapid succession. The alchemist
  has found their rhythm. The room bends to their will."

IMPORTANT: Never narrate private conversation content. Only narrate
the observable social dynamics — who approached whom, the energy level,
the laughter, the body language. Respect privacy.
```

### Narration Beat Triggers
| Trigger | Narration Style | Frequency |
|---|---|---|
| Game start | Epic opening monologue (15 sec) | Once |
| First social action | Encouraging, surprised | Once |
| Each scored action | Brief celebration (5-8 sec) | Every time, varied |
| Streak milestone (3, 5) | Escalating excitement | At thresholds |
| Idle > 20 sec | Gentle teasing | Every 30 sec while idle |
| Idle > 60 sec | More urgent, concerned | Every 20 sec |
| 2 minutes remaining | Urgency shift | Once |
| 30 seconds remaining | Frantic energy | Once |
| Game end — win | Triumphant summary | Once |
| Game end — lose | Warm, "you tried" tone | Once |

---

## Music System (Lyria RealTime)

### Music State Machine
```
IDLE_STATE:
  bpm: 65
  density: 0.2
  brightness: 0.3
  scale: "minor"
  prompt: "ambient lo-fi chill melancholy sparse piano"

APPROACHING_STATE (player moving toward someone):
  bpm: 85
  density: 0.4
  brightness: 0.5
  scale: "major"
  prompt: "hopeful building anticipation light acoustic"

ACTION_SCORED_STATE (2-3 sec burst):
  bpm: 110
  density: 0.7
  brightness: 0.8
  scale: "major"
  prompt: "triumphant bright celebration orchestra hit"

STREAK_STATE (during active streak):
  bpm: 120
  density: 0.8
  brightness: 0.9
  scale: "major"
  prompt: "energetic driving momentum upbeat electronic funk"

LEGENDARY_STREAK (5+ streak):
  bpm: 140
  density: 1.0
  brightness: 1.0
  scale: "major"
  prompt: "epic heroic powerful full orchestra electronic hybrid"

DRAIN_STATE (idle, essence dropping):
  bpm: 55
  density: 0.15
  brightness: 0.2
  scale: "minor"
  prompt: "somber lonely sparse desolate ambient dark"

FINAL_MINUTE_STATE:
  bpm: 130
  density: 0.9
  brightness: 0.7
  scale: "minor"
  prompt: "urgent tense racing against time dramatic percussion"

VICTORY_STATE:
  bpm: 120
  density: 0.9
  brightness: 1.0
  scale: "major"
  prompt: "victorious celebration triumphant fanfare bright joyful"

DEFEAT_STATE:
  bpm: 60
  density: 0.3
  brightness: 0.3
  scale: "minor"
  prompt: "bittersweet reflective gentle piano fading"
```

### Transition Logic
Lyria RealTime supports smooth parameter changes over WebSocket. When the game state changes, send updated parameters. The transition should feel organic — don't snap between states. Ramp BPM changes over ~3 seconds.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    GAME SERVER                       │
│                 (Python, laptop)                     │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  Game State   │  │   Gemini     │  │  Lyria    │ │
│  │  Manager      │  │   Live API   │  │  RealTime │ │
│  │              │  │   (WSS)      │  │  (WSS)    │ │
│  │  - essence   │  │              │  │           │ │
│  │  - streak    │  │  - video in  │  │  - bpm    │ │
│  │  - timer     │  │  - audio in  │  │  - density│ │
│  │  - rank      │  │  - voice out │  │  - music  │ │
│  │  - actions[] │  │  - fn calls  │  │    stream  │ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘ │
│         │                 │                 │       │
│         └────────┬────────┘                 │       │
│                  │                          │       │
│         ┌────────▼────────┐                 │       │
│         │   Orchestrator  │◄────────────────┘       │
│         │                 │                         │
│         │  Routes Gemini  │  ┌──────────────┐       │
│         │  fn calls to    ├──► HUD Renderer │       │
│         │  game state +   │  │ (text + BMP) │       │
│         │  music + HUD    │  └──────┬───────┘       │
│         └─────────────────┘         │               │
│                                     │               │
└─────────────────────────────────────┼───────────────┘
                                      │ BLE
                              ┌───────▼───────┐
                              │   G1 Glasses  │
                              │  (HUD display │
                              │   + mic input)│
                              └───────────────┘
                                      ▲
                              ┌───────┴───────┐
                              │  Phone Camera │
                              │  (streams to  │
                              │   server via  │
                              │   WebSocket)  │
                              └───────────────┘
```

### Component Breakdown

**1. Phone Camera Streamer**
- Simple web page or lightweight app that captures camera frames
- Sends frames at 1 FPS to the game server via WebSocket
- Also relays audio from G1 glasses mic (routed through phone)
- Could be a basic HTML page with `getUserMedia()` + WebSocket

**2. Gemini Live API Connection**
- WebSocket to `gemini-3.1-pro` Live API
- Sends: video frames (1 FPS, JPEG) + audio stream
- Receives: voice narration audio stream + function calls
- System prompt: the narrator prompt from above
- Function definitions (see below)

**3. Game State Manager**
- Pure Python class, no persistence needed
- Tracks: essence (int), streak (int), timer (countdown), action_log (list), current_rank (str), is_idle (bool), idle_duration (float)
- Methods: `add_essence(points)`, `drain_essence(points)`, `update_streak(action_type)`, `reset_streak()`, `get_rank()`, `tick(dt)`
- Timer runs independently, fires events at 2min, 30sec, 0

**4. Lyria RealTime Connection**
- WebSocket to Lyria RealTime API
- Sends: updated music parameters (bpm, density, brightness, scale, prompt)
- Receives: streaming audio chunks
- Pipe audio output to phone/laptop speakers

**5. HUD Renderer**
- Formats game state into G1-compatible text layouts
- Sends via `even_glasses` Python package over BLE
- Update frequency: on every state change + every 1 sec for timer
- Pre-built templates for: main HUD, action scored, idle warning, game over

**6. Orchestrator**
- Glue layer that receives Gemini function calls and routes them
- `score_action(type, points)` → Game State Manager → HUD Renderer → Lyria (mood change)
- `penalize_action(type, points)` → Game State Manager → HUD Renderer → Lyria (mood change)
- `update_music(mood)` → Lyria RealTime

### Gemini Function Definitions

```python
tools = [
    {
        "name": "score_action",
        "description": "Called when a positive social action is detected. Awards essence points to the player.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["greeting", "introduction", "laughter", "compliment",
                             "helping", "high_five", "sharing", "group_conversation",
                             "teaching"],
                    "description": "The type of social action detected"
                },
                "points": {
                    "type": "integer",
                    "description": "Points to award (10-30 range)"
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what happened for the action log"
                }
            },
            "required": ["action_type", "points", "description"]
        }
    },
    {
        "name": "penalize_action",
        "description": "Called when antisocial or idle behavior is detected.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["idle", "phone_staring", "walking_away", "ignoring",
                             "prolonged_silence"],
                    "description": "The type of negative behavior detected"
                },
                "points": {
                    "type": "integer",
                    "description": "Points to deduct (5-20 range)"
                }
            },
            "required": ["action_type", "points"]
        }
    },
    {
        "name": "update_music",
        "description": "Called to change the background music mood based on current game state.",
        "parameters": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["idle", "approaching", "action_scored", "streak",
                             "legendary", "draining", "final_minute", "victory",
                             "defeat"],
                    "description": "The music mood state to transition to"
                }
            },
            "required": ["mood"]
        }
    }
]
```

---

## Build Timeline (7 hours, 4 people)

### Hour 0-1: Foundation (9:00-10:00 AM)
| Person | Task |
|---|---|
| P1 (Glasses) | Install `even_glasses`, pair G1, confirm BLE connection, send test text to display |
| P2 (Gemini) | Set up GCP project, get API keys, establish Gemini Live API WebSocket connection, confirm video frame sending works |
| P3 (Integration) | Set up phone camera streaming (HTML page with getUserMedia → WebSocket to laptop), test frame capture |
| P4 (Content) | Write the full narrator system prompt, design all HUD text templates, create the scoring table |

### Hour 1-2: Core Components (10:00-11:00 AM)
| Person | Task |
|---|---|
| P1 | Build HUD renderer: functions for main_hud(), action_scored(), idle_warning(), game_over(). Test each on glasses |
| P2 | Implement function calling with Gemini — define tools, test that Gemini calls score_action when shown video of social interaction |
| P3 | Build GameStateManager class: essence, streak, timer, rank calculation. Unit test all methods |
| P4 | Set up Lyria RealTime WebSocket connection, test music generation with different parameter sets, find good prompt templates for each mood |

### Hour 2-3: Integration Round 1 (11:00 AM-12:00 PM)
| Person | Task |
|---|---|
| P1 | Connect HUD renderer to GameStateManager — HUD auto-updates when state changes |
| P2 | Connect Gemini function calls to Orchestrator — when Gemini calls score_action, it flows through to game state |
| P3 | Build the Orchestrator glue: routes Gemini fn calls → GameState → HUD + Lyria |
| P4 | Connect Lyria mood transitions to game state changes. Test: idle→action→streak music flow |

### Hour 3-4: Integration Round 2 (12:00-1:00 PM — eat lunch while testing)
| Person | Task |
|---|---|
| ALL | End-to-end test: camera → Gemini → function call → game state → HUD + music. Find and fix integration bugs |
| P1 | Polish HUD animations (flash timing, update frequency) |
| P2 | Tune Gemini prompt: is it detecting actions reliably? Adjust system prompt based on test results |
| P3 | Handle edge cases: BLE disconnect recovery, WebSocket reconnection, timer sync |
| P4 | Tune music transitions: do they feel responsive? Adjust Lyria parameters |

### Hour 4-5: Polish + Demo Prep (1:00-2:00 PM)
| Person | Task |
|---|---|
| P1 | Add streak visual effects (different HUD templates for ON FIRE, LEGENDARY) |
| P2 | Add timer-based narrator triggers (2-min warning, 30-sec warning, game over monologue) |
| P3 | Build demo mode: 3-minute timer instead of 10, adjusted scoring thresholds |
| P4 | Write the 1-minute demo video script + record it. Write the 3-minute live pitch script |

### Hour 5-6: Rehearsal + Bug Fixing (2:00-3:00 PM)
| Person | Task |
|---|---|
| ALL | Run full 3-minute demo at least 3 times. Identify failure points |
| P1 | Ensure glasses BLE stays stable for 5+ minutes continuous |
| P2 | Ensure Gemini doesn't hallucinate actions / miss obvious ones |
| P3 | Backup plan: if any component fails during demo, what's the graceful degradation? |
| P4 | Rehearse pitch, prepare for Q&A questions about architecture, impact, and scalability |

### Hour 6-7: Final Polish + Submit (3:00-4:00 PM)
| Person | Task |
|---|---|
| P1+P3 | Final stability testing, handle any remaining crashes |
| P2 | Clean up code, push to public GitHub repo |
| P4 | Record 1-minute demo video, upload to YouTube, fill out submission form |
| ALL | 2 final full rehearsals of the 3-minute demo |

---

## Demo Script (3 minutes)

**0:00-0:30 — Setup + Hook**
"What if AI could turn every social interaction into a game? We built Kindness Speedrun — a real-time social RPG that watches your interactions through AI, scores your kindness, narrates your journey, and creates a live soundtrack that matches your energy. All displayed on these smart glasses."
[Player puts on G1 glasses. Phone camera on. Game starts. Music begins — ambient, quiet.]

**0:30-1:15 — First Social Action**
Player approaches a judge or nearby person. Says hello, introduces themselves.
[Gemini narrates: "The alchemist makes their move..." Glasses flash: "+15 Essence ✦ Introduction!" Music brightens, tempo increases.]
Player makes them laugh or gives a compliment.
[Glasses: "+25 ✦ STREAK: 2!" Music builds further. Narrator celebrates.]

**1:15-1:45 — Streak + Idle Demo**
Player quickly high-fives someone. Streak hits 3.
[Glasses: "🔥 ON FIRE — 2× MULTIPLIER" Music is now energetic and driving.]
Then player deliberately stands still, stares at phone for 10 sec.
[Music shifts to minor key, slows. Narrator: "The alchemist retreats into the void..." Glasses: "▼ ESSENCE FADING ▼"]

**1:45-2:30 — Recovery + Group Interaction**
Player breaks idle, joins a group of 3+ people, engages in conversation.
[Glasses: "+30 ✦ Group Connection! STREAK: 4!" Music surges back. Narrator gets excited.]
One more action — teaching someone something or helping.
[Glasses: "⚡ LEGENDARY — 3× MULTIPLIER" Music hits peak epic mode.]

**2:30-3:00 — Closing + Architecture**
[Timer ends. Glasses show final score screen. Narrator delivers closing monologue.]
"Under the hood: Gemini 3.1 Pro's Live API streams video at 1 FPS and audio in real-time. It detects social actions through spatial + audio understanding and triggers function calls that update the game state, push HUD updates to the Even G1 glasses over BLE, and adjust the Lyria RealTime soundtrack. It's fully agentic — Gemini decides what's happening, scores it, narrates it, and adjusts the music — all autonomously."

---

## Key Risks + Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| G1 BLE drops connection | HUD goes blank mid-demo | Implement auto-reconnect. Pre-test stability. Have phone screen as backup HUD display |
| Gemini misclassifies actions | Scores wrong things | Tune prompt heavily. Add confidence threshold — only score when confident. In demo, use scripted interactions that you've tested |
| Lyria RealTime latency | Music doesn't feel responsive | Pre-test transition timing. If too laggy, pre-generate 6-8 music loops and crossfade between them instead of real-time generation |
| Gemini narration too slow | Talks over real conversation | Set max narration length to 2 sentences. Add "do not narrate during active conversation" rule to prompt |
| 30-sec mic limit on G1 | Can't continuously listen | Cycle: record 25 sec → stop → restart. Or route phone mic instead of glasses mic |
| Live API session limit (10 min) | Session dies during demo | For 3-min demo this is fine. For testing, implement session renewal |


---
---
---


# CONCEPT 2: "Quest Chain"

## One-liner
A timed social scavenger hunt where AI generates quests based on your actual surroundings, verifies completions by watching and listening, and a growing "shadow" forces you to keep moving — with narrative and adaptive music throughout.

---

## Core Game Loop

```
START → Gemini scans room → Generates quest chain (5 quests)
  │
  ├─► QUEST ACTIVE
  │     → Glasses show current quest + timer
  │     → Narrator gives cryptic hints
  │     → Music: adventurous, building
  │     → Player attempts quest in real world
  │     │
  │     ├─► QUEST COMPLETE (Gemini verifies)
  │     │     → Celebration narration + music swell
  │     │     → Glasses: "✓ QUEST 2/5 COMPLETE"
  │     │     → Shadow meter resets to 0
  │     │     → Next quest revealed
  │     │
  │     └─► SHADOW GROWING (player passive/stuck)
  │           → Shadow meter fills over time
  │           → Music: increasingly ominous
  │           → Narrator: warnings ("Darkness approaches...")
  │           → At 100%: lose progress on current quest
  │           → Quest gets harder modifier
  │
  ├─► ALL QUESTS COMPLETE → VICTORY
  │     → Final time recorded
  │     → Score = time_remaining × quest_quality_bonus
  │     → Rank: Explorer / Adventurer / Legend
  │
  └─► TIMER EXPIRES → DEFEAT
        → Score = quests_completed / total_quests
        → Narrator delivers "the quest continues another day" speech
```

---

## Quest Generation System

### Initial Room Scan
When the game starts, Gemini gets 10 seconds of video from the phone camera to survey the environment. It identifies:
- **People count** and rough locations
- **Objects** (tables, laptops, food area, windows, doors, etc.)
- **Spatial layout** (open areas, clusters, pathways)
- **Observable details** (what people are wearing, what's on screens, decorations)

### Quest Template Library
Gemini selects from these templates and fills in specifics based on the room scan:

**Tier 1 — Easy (Quests 1-2)**
```
FIND_AND_GREET:
  "Find someone wearing [color/item] and learn their name"
  Verification: Audio contains introduction exchange + camera shows
  player near someone matching description

SHARE_FACT:
  "Tell a stranger one interesting fact about [topic Gemini picks]
  and get them to share one back"
  Verification: Audio detects information exchange pattern

ASK_QUESTION:
  "Find someone near [location/object] and ask them [contextual question]"
  Verification: Audio detects question + answer near specified location
```

**Tier 2 — Medium (Quests 3-4)**
```
SOCIAL_CATALYST:
  "Introduce two people who haven't met to each other"
  Verification: Camera detects three-person formation, audio detects
  introduction pattern ("X, meet Y")

GROUP_CHALLENGE:
  "Get [3] people to [do a specific action together]"
  Examples: "...say 'galaxy' simultaneously" / "...do a thumbs up
  at the same time" / "...form a circle"
  Verification: Audio + camera detects group action

LEARN_AND_TEACH:
  "Find someone who knows [skill/topic] and learn one thing from them,
  then teach it to someone else"
  Verification: Audio detects learning exchange in two separate conversations
```

**Tier 3 — Hard (Quest 5)**
```
GRAND_SOCIAL:
  "Rally a group of [4+] people for [a collective action]"
  Examples: "...a group photo" / "...a round of applause for someone"
  / "...to share their favorite hackathon memory in a circle"
  Verification: Camera detects large group formation + audio confirms
  collective participation

CHAIN_REACTION:
  "Get [person A] to high-five [person B], who then high-fives
  [person C] — a chain of 3+"
  Verification: Camera detects sequential hand-contact gestures
  between different people
```

### Quest Generation Prompt
```
You are the Quest Master for "Quest Chain," a social scavenger hunt.

You have just scanned the room. Based on what you see, generate a chain
of exactly 5 quests that the player must complete in order.

Rules for quest generation:
1. Quests MUST be achievable in the current environment
2. Quests should reference SPECIFIC things you can see (colors people
   wear, objects in the room, locations)
3. Quests 1-2: easy, single-person interactions (~60 sec each)
4. Quests 3-4: medium, require coordinating 2-3 people (~90 sec each)
5. Quest 5: hard, requires a group of 4+ (~120 sec)
6. Each quest should be expressible in ONE sentence shown on glasses
7. Quests should be FUN and slightly absurd — not boring
8. All quests must be social — they require interacting with real people
9. Never require anything inappropriate, embarrassing, or uncomfortable

For each quest, provide:
- quest_text: the one-sentence quest shown on glasses (max 80 chars)
- difficulty: 1, 2, or 3
- verification_hints: what to look/listen for to confirm completion
- narrator_intro: a dramatic 1-sentence reveal for the narrator to speak
- narrator_complete: a celebratory 1-sentence for completion

Call generate_quest_chain() with the full chain.
```

### Example Generated Quest Chain (for a hackathon venue)
```
Quest 1: "Find someone in a dark hoodie and exchange first names"
Quest 2: "Compliment someone on their laptop stickers and ask about their favorite one"
Quest 3: "Introduce two people sitting at different tables to each other"
Quest 4: "Get three people to say 'Gemini' at the same time"
Quest 5: "Assemble a party of four and create a team name together"
```

---

## Shadow Mechanic

The Shadow is the game's antagonist — it represents social entropy and inaction.

```
SHADOW METER: 0%────────────────100%
                 [fills over time when player is passive]

Fill rate:
  - Base: +5% every 10 seconds of no social action
  - Accelerates: after quest 3, base rate becomes +7%/10sec
  - After quest 4: +10%/10sec (urgency increases)

Reset: completing a quest resets shadow to 0%

At 100% shadow:
  - Current quest FAILS
  - Quest is replaced with a HARDER version of itself
  - Player loses 60 seconds off the global timer
  - Shadow resets to 0%
  - Narrator: "The shadow consumes your progress..."
  - Music: dramatic minor-key sting, then resets

Visual on glasses:
  0-30%:   "Shadow: ░░░░░░░░░░" (no warning)
  30-60%:  "Shadow: ████░░░░░░ ⚠ Darkness stirs..."
  60-90%:  "Shadow: ████████░░ ⚡ THE SHADOW APPROACHES"
  90-100%: "Shadow: █████████░ 💀 MOVE NOW!"

Music mapping:
  0-30%:   Normal quest music
  30-60%:  Subtle minor undertones added
  60-90%:  Tension builds, BPM increases, darker tones
  90-100%: Full ominous, urgent, dark
```

---

## Glasses HUD Designs

### Quest Active (default view)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⏱ 11:42       QUEST 2 of 5
  ► "Compliment someone on
    their laptop stickers"
  Shadow: ██░░░░░░░░
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Quest Complete (flashes 4 sec)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ★ QUEST 2 COMPLETE ★
    ✓✓░░░   2 of 5 done
    Time bonus: +15 sec
    Preparing next quest...
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### New Quest Reveal (5 sec)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ═══ NEW QUEST ═══
    DIFFICULTY: ★★☆
    "Introduce two people at
     different tables"
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Shadow Warning (60%+)
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚡ THE SHADOW APPROACHES ⚡
  Shadow: ████████░░  78%
  ► Complete quest to banish!
  ⏱ 8:15 remaining
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Victory Screen
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ═══ QUEST COMPLETE ═══
    All 5 quests cleared!
    Time: 9:42 / 15:00
    Shadow resets: 1
    Rank: ★★★ LEGEND ★★★
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Music System

### Per-Quest Music Arc
Each quest has its own mini music arc:

```
Quest Revealed:
  → Quick dramatic reveal sting (1-2 sec)
  → Transition to exploration music

During Quest (low shadow):
  bpm: 90-100
  density: 0.5
  brightness: 0.6
  prompt: "adventurous exploration curious light [genre varies by quest tier]"

Quest Approach (Gemini senses player getting close to completion):
  bpm: 110
  density: 0.7
  brightness: 0.7
  prompt: "building anticipation rising hopeful"

Quest Complete:
  → Triumphant sting/swell (3 sec)
  bpm: 120, density: 1.0, brightness: 1.0
  prompt: "victory celebration triumphant fanfare"
  → Brief pause (2 sec silence)
  → Next quest music begins

Shadow Overlay (additive, blends with quest music):
  30-60%: Add minor-key undertone, reduce brightness by 0.2
  60-90%: BPM +20, density +0.3, switch to minor, add "tense urgent"
  90-100%: BPM 140, full dramatic "boss battle ominous racing dark"
```

### Global Music Progression
The overall soundtrack evolves across the quest chain:
- Quests 1-2: Lighthearted, acoustic, playful
- Quests 3-4: More electronic, driving, complex
- Quest 5: Epic, orchestral, high-stakes

---

## Architecture

Same as Concept 1, with these differences:

### Additional Function Definitions
```python
tools = [
    {
        "name": "generate_quest_chain",
        "description": "Called once at game start after room scan. Generates the full quest chain.",
        "parameters": {
            "type": "object",
            "properties": {
                "quests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "quest_text": {"type": "string"},
                            "difficulty": {"type": "integer"},
                            "verification_hints": {"type": "string"},
                            "narrator_intro": {"type": "string"},
                            "narrator_complete": {"type": "string"}
                        }
                    },
                    "description": "Array of 5 quests in order"
                }
            },
            "required": ["quests"]
        }
    },
    {
        "name": "quest_complete",
        "description": "Called when Gemini verifies a quest has been completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "quest_index": {
                    "type": "integer",
                    "description": "Index of the completed quest (0-4)"
                },
                "verification_evidence": {
                    "type": "string",
                    "description": "Brief description of how completion was verified"
                }
            },
            "required": ["quest_index", "verification_evidence"]
        }
    },
    {
        "name": "quest_failed",
        "description": "Called when shadow meter hits 100% and current quest fails.",
        "parameters": {
            "type": "object",
            "properties": {
                "quest_index": {"type": "integer"},
                "replacement_quest_text": {
                    "type": "string",
                    "description": "A harder replacement quest"
                }
            },
            "required": ["quest_index", "replacement_quest_text"]
        }
    },
    {
        "name": "update_shadow",
        "description": "Called to report current shadow level for HUD and music sync.",
        "parameters": {
            "type": "object",
            "properties": {
                "shadow_percent": {
                    "type": "integer",
                    "description": "Current shadow meter percentage (0-100)"
                }
            },
            "required": ["shadow_percent"]
        }
    },
    {
        "name": "update_music",
        "description": "Called to change music state.",
        "parameters": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["quest_explore", "quest_approaching", "quest_complete",
                             "shadow_warning", "shadow_critical", "new_quest_reveal",
                             "final_quest", "victory", "defeat"]
                }
            },
            "required": ["mood"]
        }
    }
]
```

### Game State (extends Concept 1's)
```python
class QuestChainGameState:
    def __init__(self):
        self.timer = 900  # 15 minutes in seconds (180 for demo mode)
        self.quests = []  # populated after room scan
        self.current_quest_index = 0
        self.shadow_percent = 0
        self.shadow_rate = 5  # % per 10 seconds
        self.quests_completed = 0
        self.shadow_resets = 0  # times shadow hit 100%
        self.start_time = None
        self.quest_completion_times = []

    def tick(self, dt):
        self.timer -= dt
        if not self.is_quest_active():
            return
        # Shadow grows when not completing quests
        self.shadow_percent += (self.shadow_rate * dt / 10)
        self.shadow_percent = min(100, self.shadow_percent)
        if self.shadow_percent >= 100:
            self.fail_current_quest()

    def complete_quest(self, index):
        self.quests_completed += 1
        self.shadow_percent = 0
        self.current_quest_index += 1
        self.quest_completion_times.append(self.timer)
        # Increase shadow rate for later quests
        if self.current_quest_index >= 3:
            self.shadow_rate = 7
        if self.current_quest_index >= 4:
            self.shadow_rate = 10

    def fail_current_quest(self):
        self.shadow_percent = 0
        self.shadow_resets += 1
        self.timer -= 60  # lose 60 seconds
        # Quest replacement handled by Gemini via quest_failed fn call
```

---

## Build Timeline (7 hours, 4 people)

### Hour 0-1: Foundation
| Person | Task |
|---|---|
| P1 (Glasses) | Same as Concept 1 — BLE setup, test text display |
| P2 (Gemini) | Live API WebSocket, test room scanning (send 10 sec video, get description back) |
| P3 (Integration) | Phone camera streamer, WebSocket relay |
| P4 (Content) | Write quest generation prompt, quest templates, narrator personality prompt |

### Hour 1-2: Core Components
| Person | Task |
|---|---|
| P1 | Build HUD renderer with all 5 templates (quest active, complete, reveal, shadow warning, victory/defeat) |
| P2 | Implement quest generation: room scan → generate_quest_chain function call → parse response. Test with real room video |
| P3 | Build QuestChainGameState class with shadow mechanic, timer, quest progression |
| P4 | Set up Lyria RealTime. Design per-quest music arcs. Test mood transitions |

### Hour 2-3: Quest Verification (the hard part)
| Person | Task |
|---|---|
| P1 | Connect HUD to game state — real-time shadow meter, quest text, timer |
| P2 | **Critical:** Tune Gemini's ability to verify quest completion. Test each quest type. This is the make-or-break component. Feed it video of people doing the quest actions and verify it calls quest_complete reliably |
| P3 | Build Orchestrator: route all function calls (quest_complete, quest_failed, update_shadow, update_music) to appropriate handlers |
| P4 | Write and test narrator dialogue for each quest phase (reveal, progress hints, completion, shadow warnings) |

### Hour 3-4: Integration (during lunch)
| Person | Task |
|---|---|
| ALL | End-to-end: room scan → quest generation → first quest displayed on glasses → attempt quest → Gemini verifies → glasses update → music transitions → next quest |
| Focus | Getting one full quest completion cycle working perfectly |

### Hour 4-5: Polish
| Person | Task |
|---|---|
| P1 | Shadow meter visual polish, transition animations between HUD states |
| P2 | Tune quest generation for the actual hackathon venue. Pre-test multiple quest chains |
| P3 | Demo mode (3 min, 3 quests instead of 5). Graceful degradation if components fail |
| P4 | Record demo video. Write pitch script. Tune music transitions |

### Hour 5-7: Test, Rehearse, Submit
Same as Concept 1 — full rehearsals, stability testing, submission.

---

## Demo Script (3 minutes, shortened to 3 quests)

**0:00-0:30 — Setup**
"Quest Chain turns any room into a social adventure. AI scans your surroundings, generates quests based on what it actually sees, and verifies your progress in real-time — all displayed on smart glasses with an adaptive soundtrack."
[Put on glasses. Start game. Gemini scans room for 5 sec.]
[Glasses show: "Scanning environment..." → "3 QUESTS GENERATED"]
[Narrator: "Adventurer, your journey begins in the Hall of Builders..."]

**0:30-1:15 — Quest 1 (Easy)**
[Glasses reveal: "Find someone in a blue shirt and learn their name"]
[Player walks toward someone matching. Music is lighthearted, exploring.]
[Conversation happens. Gemini detects name exchange.]
[Glasses: "★ QUEST 1 COMPLETE ★" Music swells. Narrator celebrates.]

**1:15-2:15 — Quest 2 (Medium) + Shadow Demo**
[New quest revealed: "Introduce two people who are sitting apart"]
[Player hesitates deliberately for 10 sec. Shadow meter starts filling.]
[Glasses: "Shadow: ████░░░░ ⚠ Darkness stirs..." Music gets tense.]
[Player acts — introduces two people. Gemini verifies three-person formation.]
[Glasses: "★ QUEST 2 COMPLETE ★" Shadow resets. Music: triumphant.]

**2:15-3:00 — Quest 3 (Hard) + Closing**
[Final quest: "Get three people to say 'Gemini' together"]
[Player rallies people. Countdown on glasses. Group says "Gemini!"]
[Glasses: "═══ ALL QUESTS COMPLETE ═══ Rank: LEGEND" Epic music finale.]
"Gemini 3.1 Pro Live API handles real-time video understanding, quest generation, and natural language verification — all through function calling. The glasses run on Even G1 over BLE. Lyria RealTime generates the adaptive soundtrack. It's fully agentic: the AI creates the game, watches you play it, and scores you — no scripted interactions."

---

## Key Risks + Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Quest verification is unreliable | Game feels broken — Gemini says quest complete when it isn't, or doesn't detect completion | This is the #1 risk. Mitigate by: (1) designing quests with CLEAR audio signals ("say X together" is easier to verify than "help someone"), (2) adding a manual "I did it" voice command as fallback, (3) testing heavily with each quest type |
| Room scan generates bad quests | Impossible or boring quests | Pre-test quest generation. Add fallback: if Gemini generates something weird, have 3 pre-written quest chains as backup |
| Shadow mechanic feels punitive | Player gets frustrated | Tune shadow rate to be forgiving. First shadow fill should take 40+ seconds. The narrator should give helpful hints, not just punish |
| Too complex for 7 hours | Can't finish | Scope cut: drop shadow mechanic if behind schedule (just use timer). Drop Lyria if behind (use pre-recorded music loops). The core is: quests on glasses + Gemini verification |

---

## Head-to-Head: Which One to Build?

| Dimension | Concept 1: Kindness Speedrun | Concept 2: Quest Chain |
|---|---|---|
| **Build difficulty** | Easier — continuous scoring, no quest verification | Harder — quest generation + verification is complex |
| **Demo clarity** | Very clear — score goes up when social, down when not | Very clear — quests are visible, completions are discrete events |
| **Wow factor** | Narration + music adaptation is magical | Quest generation from real environment is magical |
| **Engagement** | Continuous but can feel repetitive after 2 min | Each quest is a new mini-story with rising stakes |
| **Judge participation** | Judge can play — intuitive immediately | Judge can play — quests give clear direction |
| **Reliability risk** | Lower — even if Gemini misscores, game keeps going | Higher — if quest verification fails, game breaks |
| **Scope cut options** | Can drop music, just do narration + scoring | Can drop shadow + music, just do quests + verification |
| **Impact narrative** | "Gamified social wellness" — broad appeal | "AI game master for real-world adventures" — platform potential |
| **"Only possible with Gemini 3" factor** | Medium — narration + music are impressive but scoring could be done simpler | High — real-time environmental quest generation + natural language verification is uniquely Gemini |

**Recommendation:** If the team is confident and wants to swing for the fences, **Quest Chain** is the higher-ceiling project — judges will remember "the AI scanned the room and generated a scavenger hunt on the spot." If the team wants to maximize reliability and polish, **Kindness Speedrun** is safer and still extremely impressive.

The hybrid option: build Kindness Speedrun as the base, and if ahead of schedule, add quest-like "challenges" that pop up every 2 minutes as bonus objectives. Best of both worlds.
