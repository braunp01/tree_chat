# Requirements Document

<!--
What this file is for: WHAT the system must do, in testable sentences. Not how (design.md) and
not which tools (tech.md).

Habits that kept this file useful:
- One requirement per user goal; every acceptance criterion testable by a person or a test.
- Name the system part in the sentence (Backend_API, Front_End, Host), so it is clear which
  part is bound. A limit that is only in the screen, not in the server, must say so.
- Numbers are permanent. Never renumber or reuse one: other documents, code comments and tests
  cite them. To withdraw a requirement, keep its heading and mark it Retired (see the example
  at the end), saying what replaced it.
- When a feature changes or contradicts an earlier requirement, AMEND that requirement in
  place and add the new one; do not leave both standing.
- Say what the system deliberately does NOT do (for example, "no sign-in") where a reader would
  otherwise assume it does, and record the owner's reason and date.
- Validation rules: say which field the error names.
-->

> **Status: approved by the owner, 11 Oct 2026.**

## Introduction

Tree Chat is a local chat client for one person talking to an LLM. It addresses one problem:
in a linear chat, a tangent either derails the main thread or gets suppressed and lost. In Tree
Chat a tangent becomes a Branch anchored to the exact passage that prompted it. It can be
spawned without leaving the current thread, parked in a queue, resumed later and closed with a
short Conclusion that is merged back as a Note. The whole conversation is a visible tree.

The tool must **discourage rabbit-holing as well as enable tangents**. Closing a Branch with a
Conclusion is a first-class operation, not an afterthought.

What the model sees is a **quality decision, not a cost decision**. There is one context rule:
every Branch inherits what its parent knew at the Fork_Point (owner's decision, 11 Oct 2026). What
was sent for every reply is recorded exactly and can be inspected.

In scope for v1: one user, one machine, one LLM provider, many Trees.

Deliberately absent from v1 (owner's decision, confirmed 11 Oct 2026):
multi-user use, sign-in, sync between machines, mobile layout, Branches with more than one
Anchor, any context mode other than inheriting (no Clean mode, no trunk-summary mode, no
pinning: owner's decision, 11 Oct 2026), and deleting anything (see Req 16.3). Future capabilities reuse the same Branch, Anchor and Context rules.

## Glossary

- **Tree**: one whole conversation. It has exactly one Trunk and any number of Branches below it.
- **Trunk**: the root Branch of a Tree. It has no Anchor, no Fork_Point and no Framing_Block, and
  it is always Open.
- **Branch**: a linear sequence of Messages within a Tree, with exactly one parent Branch (except
  the Trunk). Branches form a strict tree, never a DAG. A Branch is a Tangent or an Alternative.
- **Tangent**: a Branch spawned from a passage to explore a side question. It carries an Intent,
  and a Framing_Block.
- **Alternative**: a Branch created by editing a user Message or regenerating an assistant Message.
  It continues the same conversation differently. It has no Intent and no Framing_Block, and it
  always inherits.
- **Message**: an immutable unit of conversation with role `user`, `assistant` or `note`. Messages
  are never edited or deleted.
- **Note**: a Message with role `note` that a Merge appends to a target Branch. It carries a
  Conclusion into that Branch's future context. A Note is not a user or assistant message.
- **Anchor**: the passage a Branch is about: one Message plus a start and end offset and the
  quoted text. Anchoring a whole Message is the case where the span covers all of its text.
- **Fork_Point**: the Message up to which a Branch knows its parent's conversation. It is
  separate from the Anchor. For a Tangent it defaults to the Anchor's Message; the alternative
  is the parent's Tip at spawn.
- **Tip**: the last Message of a Branch, or its Fork_Point when it has no Messages yet.
- **Intent**: the optional one-line statement of what a Tangent is for, written by the user.
- **Generated_Intent**: a one-line description written by the model when the user gave no
  Intent. It is always labelled as generated, it is used for display only and it never enters
  any Context.
- **Status**: one of `parked`, `open` or `closed`. Status is about the work, not about what is
  on screen.
- **Queue**: the Branches of a Tree whose Status is `parked`.
- **Inherited_Prefix**: what every Branch except the Trunk receives from its parent: the
  parent's own Context as it stood at the Fork_Point. This includes the parent's
  Inherited_Prefix, the parent's Framing_Block, and the parent's Messages up to and including the
  Fork_Point. It is not simply the Messages on the path from the Trunk, because it also carries
  every ancestor's Framing_Block.
- **Framing_Block**: the text that tells the model it is in a Tangent: the Anchor quote, the
  Intent (if the user wrote one) and an instruction to stay on the tangent.
- **Context**: everything sent to the model for one reply.
- **Context_Manifest**: the exact, ordered record of a Context (node ids, Framing_Block text,
  model and generation settings), stored with every assistant Message.
- **Conclusion**: the short text that records what a closed Branch found or decided.
- **Outcome**: how a Branch was closed: `merged`, `kept` or `abandoned`.
- **Merge**: closing with Outcome `merged`. It appends a Note holding the Conclusion to a target
  Branch. It never rewrites history.
- **Anchor_Marker**: the persistent margin mark beside an anchored passage, showing the Status
  of the Branch (or Branches) anchored there.
- **Path_View**: the main reading pane for one Branch: what that Branch knows, then its own
  Messages.
- **Outline**: the tree of Branches (not Messages) shown beside the Path_View.
- **Tree_Map**: a zoomable picture of the whole Tree. It shows more detail as the user zooms in:
  Macro_Branches when zoomed out, then individual Tracks, then individual Messages.
- **Track**: how the Tree_Map draws one Branch: a horizontal line that starts below its parent's
  Track, at the position of its Anchor, and is as long as the Branch's Messages.
- **Macro_Branch**: a whole subtree drawn on the Tree_Map as one labelled shape, because at the
  current zoom it would be too small to read as separate Tracks. It is a way of drawing, not a
  stored thing.
- **Conversation_Position**: how far into the conversation a Message is: the number of Messages
  before it on its path from the Trunk's first Message. It is the Tree_Map's horizontal axis.
- **Backend_API**: the local HTTP server. It is the authority on every rule below.
- **Front_End**: the browser interface. A limit enforced only there is a convenience.
- **Store**: the local database file.

## Requirements

### Requirement 1: Trees

**User Story:** As the user, I want separate conversations, each with its own tree, so that
unrelated topics do not share one tree.

#### Acceptance Criteria

1. WHEN the user creates a Tree, THE Backend_API SHALL create it with a Trunk that has no Messages and return both.
2. THE Front_End SHALL list Trees, most recently active first, showing each Tree's title and its counts of `open` and `parked` Branches.
3. WHEN the user sends the first Message of a Tree that has no title, THE Backend_API SHALL set the title to the first 60 characters of that Message. The user may rename a Tree at any time.
4. IF a Tree title is empty or longer than 200 characters after trimming, THEN THE Backend_API SHALL reject it without persisting anything and return a validation error identifying the `title` field.

### Requirement 2: Sending a message and receiving a reply

**User Story:** As the user, I want to send a message in any Branch and see the reply as it is
written, so that the conversation feels like an ordinary chat.

#### Acceptance Criteria

1. WHEN the user sends a non-empty Message in a Branch whose Status is not `closed`, THE Backend_API SHALL persist it as the new Tip of that Branch before any model call is made.
2. WHEN a Branch's Tip is a user Message and a reply is requested, THE Backend_API SHALL assemble the Context (Req 7), call the model, stream the reply text to the Front_End as it arrives, and persist the complete assistant Message with its Context_Manifest when the model finishes.
3. IF the model call fails or is refused, THEN THE Backend_API SHALL persist no assistant Message, keep the user Message, report the error category to the Front_End, and allow the reply to be requested again.
4. IF the model stops because it reached its output limit, THEN THE Backend_API SHALL persist the reply, and THE Front_End SHALL mark it as cut off.
5. WHILE a reply is being generated in a Branch, THE Backend_API SHALL reject a further Message or reply request in that same Branch with a `busy` error. Other Branches are unaffected.
6. WHEN the Front_End disconnects during generation, THE Backend_API SHALL finish and persist the reply anyway. Reopening the Branch shows it, or shows it still in progress.
7. IF Message content is empty after trimming or longer than 100,000 characters, THEN THE Backend_API SHALL reject it without persisting anything and return a validation error identifying the `content` field.
8. WHEN the user sends a Message in a `parked` Branch, THE Backend_API SHALL change its Status to `open` (Req 10.3).
9. IF the Tip of a Branch is a user Message (its reply is pending, failed or was refused), THEN THE Backend_API SHALL reject a further user Message in that Branch with a `conflict` error, so that a Framing_Block is always followed by an assistant turn. The user may request the reply again (Req 2.3) or edit that Message (Req 3.2).

### Requirement 3: Immutable messages and Alternatives

**User Story:** As the user, I want to edit a message or regenerate a reply without losing the
original, so that I can compare and nothing I wrote disappears.

#### Acceptance Criteria

1. THE Store SHALL never change or delete a persisted Message or Context_Manifest. An attempt to do so SHALL fail.
2. WHEN the user edits a user Message, THE Backend_API SHALL create an Alternative whose parent is the Branch that owns the edited Message. The Alternative's Anchor is the whole edited Message, its Fork_Point is the edited Message's predecessor, and its first Message is the edited text.
3. WHEN the user regenerates an assistant Message, THE Backend_API SHALL create an Alternative in the same way. Its first Message is a new reply generated from the same predecessor.
4. THE Front_End SHALL show, on a Message that has Alternatives, how many exist and a control to move between them. The original stays where it was.
5. THE Backend_API SHALL give an Alternative the same Inherited_Prefix rules as a Tangent, with no Framing_Block of its own. WHERE the Alternative replaces the first Message of a Tangent, it stands where that Message stood, so its Context carries that Tangent's Framing_Block immediately after the Alternative's first Message (Req 7.1).

### Requirement 4: Spawning a Tangent from a passage

**User Story:** As the user, I want to select a passage in any message and spawn a Tangent from
it without leaving where I am, so that I can capture the thought and keep going.

#### Acceptance Criteria

1. WHEN the user selects text within a single Message (user, assistant or Note) in the Path_View, THE Front_End SHALL show a popover beside the selection with a one-line Intent field that already has focus.
2. WHEN the user presses Enter in the popover, THE Front_End SHALL spawn the Tangent with Status `parked` and keep the current view unchanged. WHEN the user presses Ctrl+Enter (Cmd+Enter on macOS), it SHALL spawn the Tangent with Status `open` and navigate to it. Escape SHALL dismiss the popover without creating anything.
3. THE Intent SHALL be optional. IF it is longer than 200 characters after trimming, THEN THE Backend_API SHALL reject the spawn and return a validation error identifying the `intent` field.
4. WHEN a Tangent is spawned, THE Backend_API SHALL make its parent the Branch that owns the Anchor's Message, whichever Branch's Path_View the selection was made in.
5. IF the Anchor's start or end offset is out of range, if start is not less than end, or if the quoted text does not equal the Message text between the offsets, THEN THE Backend_API SHALL reject the spawn and return a validation error identifying the `anchor` field.
6. IF a selection spans more than one Message, THEN THE Front_End SHALL not offer the popover.
7. THE Backend_API SHALL accept Tangents spawned from any Branch at any depth. There is no depth limit.
8. WHEN a Tangent is spawned, THE Backend_API SHALL set its Fork_Point to the Anchor's Message unless the request asks for the parent's Tip.
9. WHEN a Tangent is spawned without an Intent, THE Backend_API SHALL generate a Generated_Intent from the Anchor and the Anchor's Message in the background. Spawning SHALL not wait for it, and it SHALL never be used in a Framing_Block (Req 11).
10. WHERE the parent Branch has Notes after the Anchor's Message, THE Front_End SHALL say so in the popover and offer Fork_Point "at the latest message" (Req 9.1), because a Tangent forked at the passage will not see those Notes (Req 13.6).

### Requirement 5: Anchor markers

**User Story:** As the user, I want to see in the margin which passages have Branches and what
state they are in, so that the tree is visible from inside the conversation.

#### Acceptance Criteria

1. THE Front_End SHALL show an Anchor_Marker beside every anchored passage wherever its Message is displayed, including in the inherited part of a Path_View. The marker distinguishes `parked`, `open` and `closed`.
2. THE Front_End SHALL highlight the anchored passage when its marker is hovered or focused, and show the Intent (or Generated_Intent, labelled) of each Branch anchored there.
3. WHEN several Branches anchor in the same Message, THE Front_End SHALL show one marker per distinct passage, with a count where passages coincide.
4. WHEN the user activates an Anchor_Marker, THE Front_End SHALL navigate to that Branch, or offer a choice when more than one Branch is anchored there. The Branch's Status does not change.

### Requirement 6: Tree structure

**User Story:** As the user, I want the structure to stay a plain tree, so that I always know
where a Branch came from.

#### Acceptance Criteria

1. THE Backend_API SHALL give every Branch except the Trunk exactly one parent Branch in the same Tree and exactly one Anchor, and SHALL reject any change that would create a cycle or a second parent.
2. THE Backend_API SHALL ensure that every Branch's Messages form a single chain: the first Message follows the Fork_Point, and each later Message follows the one before it.
3. THE Backend_API SHALL ensure that a Branch's Fork_Point lies on the path from the Trunk's first Message to the parent's Tip, or is empty only for an Alternative of a Branch's very first Message.

### Requirement 7: Context assembly

**User Story:** As the user, I want each Branch to send the model exactly the conversation I
chose, and to be able to see what was sent, so that I can trust and reproduce what it knew.

#### Acceptance Criteria

1. THE Backend_API SHALL build each Context for a Tangent as: Inherited_Prefix, then the Branch's own Messages, with the Framing_Block placed once, immediately after the Branch's first user Message (so the model reads it before writing anything in the Branch). For an Alternative it is the same without a Framing_Block, and for the Trunk it is the Trunk's own Messages.
2. (Retired: this was Clean mode, withdrawn by the owner on 11 Oct 2026; every Branch inherits. The number is kept so that references stay valid.)
3. THE Framing_Block SHALL contain the Anchor's quoted text, the Intent if the user wrote one, and an instruction to stay on the tangent. It SHALL be fixed when the Branch receives its first Message and SHALL not change afterwards, even if the Intent label is edited.
4. THE Backend_API SHALL make Context assembly deterministic: the same Store contents and settings always give byte-identical model requests.
5. THE Backend_API SHALL render the Inherited_Prefix of sibling Branches that share a parent and a Fork_Point byte-identically, so the provider's prefix cache can be reused.
6. THE Backend_API SHALL ensure that a Branch's Inherited_Prefix never changes once the Branch has its first Message. Later Messages and Notes in the parent come after the Fork_Point, so they SHALL not alter it. Each Context in a Branch extends the previous one: nothing earlier is removed, reordered or changed.
7. WHEN an assistant Message is persisted, THE Store SHALL persist its Context_Manifest with it: the ordered list of Message ids and Framing_Blocks sent, the model id and the generation settings.
8. WHEN the user asks to inspect an assistant Message's context, THE Front_End SHALL show its Context_Manifest as the list of Messages and Framing_Blocks that were sent, in order.
9. THE Backend_API SHALL include Notes in a Context at their position in the chain, labelled as Notes, never as something the user said.
10. IF an assembled Context exceeds the model's input limit, THEN THE Backend_API SHALL persist nothing for the reply and return a `context_too_large` error. (With a 1M-token model this needs an exceptionally deep Tree.)

### Requirement 8: Switching context mode mid-branch (Retired)

**Retired.** The owner withdrew context modes on 11 Oct 2026, so there is nothing to switch:
every Branch inherits (Req 7.1). The numbers of the other requirements are unchanged so that
existing references stay valid.

### Requirement 9: Choosing and changing the Fork_Point

**User Story:** As the user, I want to choose whether a Tangent knows only the conversation up to
the anchored passage or everything up to now, so that a tangent resumed later can catch up.

#### Acceptance Criteria

1. WHEN spawning a Tangent, THE Front_End SHALL offer Fork_Point "at the passage" (default) or "at the latest message".
2. WHILE a Tangent has no Messages, THE Backend_API SHALL allow its Fork_Point to be changed between the Anchor's Message and the parent's current Tip.
3. IF a Fork_Point change is requested for a Branch that has Messages, THEN THE Backend_API SHALL reject it with a validation error identifying the `fork_point` field.

### Requirement 10: Parking, resuming and the Queue

**User Story:** As the user, I want tangents I am not pursuing now to wait in a queue I can triage,
so that thoughts are kept without derailing me.

#### Acceptance Criteria

1. THE Backend_API SHALL allow these Status changes and reject any other with a `conflict` error: `parked` to `open` (resume), `open` to `parked` (park), `parked` or `open` to `closed` (close, Req 12), and `closed` to `open` (reopen, Req 12.7). The Trunk's Status cannot change.
2. THE Front_End SHALL show the Queue for the current Tree. Each entry shows the Intent first, or the Generated_Intent labelled as generated when there is no Intent, then the Anchor quote, the parent Branch, and how long ago it was parked.
3. WHEN the user resumes a Branch from the Queue, THE Backend_API SHALL set its Status to `open`, and THE Front_End SHALL navigate to it. Navigating to a `parked` Branch without resuming it SHALL not change its Status.
4. THE Front_End SHALL order the Queue oldest-parked first by default, with a switch to newest first and a switch to group by parent Branch.
5. THE Front_End SHALL show each Queue entry's staleness as facts: time since parked, and how many Messages the parent Branch has gained since the Fork_Point. Nothing is closed or hidden automatically.
6. WHEN the user resumes a Tangent that has no Messages and whose parent has moved on past its Fork_Point, THE Front_End SHALL offer to move the Fork_Point to the parent's current Tip (Req 9.2).
7. THE Front_End SHALL let the user close Branches from the Queue directly, including as `abandoned`, without opening them.
8. Navigating away from an `open` Branch SHALL not change its Status. Several Branches may be `open` at once.

### Requirement 11: Generated descriptions

**User Story:** As the user, I want a short description of a branch I did not label, so that I can
triage the Queue quickly.

#### Acceptance Criteria

1. WHEN a Tangent is spawned without an Intent, THE Backend_API SHALL generate a Generated_Intent (one line, at most 120 characters) from the Anchor quote and the Anchor's Message only.
2. WHEN a Tangent that has at least one assistant Message is parked, THE Backend_API SHALL generate a one-line "where it stands" summary of the Branch's own Messages and show it in the Queue below the Intent.
3. IF generation fails, THEN THE Front_End SHALL show the Anchor quote in place of the missing text. Nothing else is blocked.
4. WHEN the user writes an Intent for a Tangent that has a Generated_Intent, THE Front_End SHALL show the user's Intent instead. The generated one is kept in the Store but not shown.
5. THE Backend_API SHALL never place a Generated_Intent or summary in any Context.

### Requirement 12: Closing a Branch

**User Story:** As the user, I want closing a tangent to be quick and to leave a record of what it
found, so that finishing tangents is easier than leaving them open.

#### Acceptance Criteria

1. WHEN the user asks to close a Tangent, THE Front_End SHALL show a close panel containing a Conclusion field pre-filled with a model-drafted Conclusion of the Branch's own Messages, which the user may edit, and a choice of Outcome: `merged` (default), `kept` or `abandoned`.
2. IF the Outcome is `merged` or `kept` and the Conclusion is empty after trimming, THEN THE Backend_API SHALL reject the close and return a validation error identifying the `conclusion` field. For `abandoned` the Conclusion is optional.
3. IF the Conclusion is longer than 2,000 characters, THEN THE Backend_API SHALL reject the close and return a validation error identifying the `conclusion` field.
4. WHEN a Branch is closed, THE Backend_API SHALL record the Outcome, the Conclusion and the time, set the Status to `closed`, and keep every Message.
5. WHEN a Branch is closed, THE Front_End SHALL navigate to the merge target (for `merged`) or the parent Branch (otherwise), scrolled to the Branch's Anchor.
6. WHEN the user closes a Branch that has descendants that are not `closed`, THE Front_End SHALL list them and offer to close them as `abandoned` in the same action. They stay as they are unless the user accepts.
7. WHEN the user reopens a `closed` Tangent, THE Backend_API SHALL set it to `open` and keep the earlier closing record and any Note it produced. A later close adds a new closing record.
8. WHILE a Branch is `closed`, THE Backend_API SHALL reject new Messages in it with a `conflict` error.
9. THE Backend_API SHALL reject closing the Trunk. An Alternative may be closed with any Outcome except `merged`.

### Requirement 13: Merging a Conclusion

**User Story:** As the user, I want a Conclusion to flow back into the conversation it came from,
so that what the tangent found is available where it matters.

#### Acceptance Criteria

1. WHEN a Branch is closed with Outcome `merged`, THE Backend_API SHALL append one Note to the target Branch as its new Tip, in the same transaction as the close.
2. THE Note SHALL contain the Conclusion and identify the source Branch by its Intent (or Anchor quote) and its Anchor quote. format in design.md.
3. THE merge target SHALL default to the parent Branch and MAY be any ancestor of the closing Branch whose Status is not `closed`.
4. IF the merge target is not such an ancestor, THEN THE Backend_API SHALL reject the close without persisting anything and return a validation error identifying the `merge_target` field.
5. IF the merge target has a reply in progress, THEN THE Backend_API SHALL reject the close with a `busy` error. IF the target's Tip is a user Message awaiting its reply, THEN it SHALL reject the close with a `conflict` error (Req 2.9).
6. THE Backend_API SHALL never change existing Messages to merge. A Note affects only Contexts built after it: later replies in the target Branch, and Branches whose Fork_Point is the Note or a later Message.
7. THE Front_End SHALL show a Note in the target's Path_View as a distinct block with a link to the source Branch.

### Requirement 14: Seeing and navigating the tree

**User Story:** As the user, I want to see the shape of the whole tree and where I am in it,
zooming out to a few macro-branches and drilling down to individual messages, without it
becoming unreadable, so that I can move around confidently.

#### Acceptance Criteria

1. THE Front_End SHALL show an Outline of the current Tree's Branches (one row per Branch, not per Message), indented by depth. Each row shows Status, Intent (or labelled Generated_Intent), Kind (Tangent or Alternative) and Message count.
2. THE Front_End SHALL expand the Outline along the path to the current Branch and collapse `closed` Branches by default. Every node can be expanded and collapsed.
3. THE Front_End SHALL show a breadcrumb of the current Branch's ancestry, from the Trunk down, with each level clickable.
4. THE Front_End SHALL show in the Path_View, for any Branch other than the Trunk, its Inherited_Prefix collapsed to a one-line summary ("N earlier messages from …") with the Anchor's Message always visible; then a framing card (Anchor quote, Intent, Fork_Point); then the Branch's own Messages.
5. (Retired with Clean mode, 11 Oct 2026.)
6. THE Front_End SHALL support keyboard navigation of the Outline: up and down to move, left and right to collapse and expand, Enter to open.
7. THE Front_End SHALL remain usable with at least 500 Branches and 10,000 Messages in one Tree. Opening a Branch then completes within one second on the owner's machine.
8. THE Front_End SHALL open the Tree_Map of the current Tree from any view with one key (`M`), and close it with the same key or Escape, returning to the view the user left.
9. THE Tree_Map SHALL draw every Branch as a Track. The horizontal axis is Conversation_Position. A Track starts at the Conversation_Position of its Anchor's Message and lies below its parent's Track, below any earlier siblings and their subtrees. Siblings are ordered by Anchor position, then by creation time.
10. WHILE a subtree would be drawn smaller on screen than the readable minimum, THE Tree_Map SHALL draw it as one Macro_Branch. Its label shows the root Branch's Intent (or labelled Generated_Intent), the number of Branches in it, and how many of them are `open` and `parked`.
11. WHEN the user zooms in (mouse wheel, pinch, `+`, or activating a Macro_Branch), THE Tree_Map SHALL expand Macro_Branches into their Tracks as they become large enough to read. WHEN the user zooms out, it SHALL collapse them again. Activating a Macro_Branch zooms until it fills the view.
12. THE Tree_Map SHALL draw every Branch exactly once at every zoom: either as its own Track or inside exactly one Macro_Branch.
13. THE Tree_Map SHALL always expand the path from the Trunk to the current Branch, at every zoom, and mark the current Branch and its Tip as "you are here".
14. WHERE a Track is drawn long enough for its Messages to be told apart, THE Tree_Map SHALL show one tick per Message (user, assistant and Note distinguishable) and mark where child Tracks leave it. Hovering a tick shows the start of that Message. Activating it opens that Branch in the Path_View, scrolled to that Message.
15. THE Tree_Map SHALL show each Track's Status with the same visual coding as Anchor_Markers, and draw `closed` Branches muted.
16. THE Tree_Map SHALL support pan and zoom from the keyboard (arrow keys, `+` and `-`) as well as the pointer. Activating a Track opens that Branch.
17. THE Tree_Map SHALL pan and zoom smoothly (at least 30 frames per second on the owner's machine) with 500 Branches and 10,000 Messages.
18. WHEN the user zooms in or out, THE Tree_Map SHALL never collapse something that a smaller zoom showed expanded at the same place, so detail does not flicker in and out.

### Requirement 15: Discouraging rabbit-holing

**User Story:** As the user, I want gentle, constant reminders of how deep I am and what is
outstanding, so that I return to the main thread on purpose rather than by accident.

#### Acceptance Criteria

1. THE Front_End SHALL always show the current depth (Trunk = 0) and the Tree's counts of `open` and `parked` Branches.
2. WHERE the nudge setting is above zero, WHEN a Tangent reaches that many assistant replies (default 8), and again at each further multiple, THE Front_End SHALL show a non-blocking prompt offering Close, Park or Continue.
3. THE Front_End SHALL make Close reachable with one keyboard shortcut from any Tangent.

### Requirement 16: Local persistence

**User Story:** As the user, I want everything kept in one local file that survives restarts and
upgrades, so that I never lose a conversation.

#### Acceptance Criteria

1. THE Store SHALL keep all Trees, Branches, Messages, Context_Manifests, closing records and Status history in one local database file.
2. WHEN the Backend_API starts with a Store created by an earlier version, it SHALL bring the Store up to date without losing data. This is safe to run on every start.
3. THE Backend_API SHALL offer no deletion of Trees, Branches or Messages in v1. (Closing and abandoning are the way to put things away.)
4. THE Backend_API SHALL record every Status change with its time, so that Queue ages and staleness can be derived.
5. IF any write in an operation fails, THEN THE Store SHALL keep none of that operation's writes.

### Requirement 17: Model provider and secrets

**User Story:** As the user, I want to choose the model in one setting and keep my API key out of
the project, so that the setup is simple and safe.

#### Acceptance Criteria

1. THE Backend_API SHALL use one LLM provider, set in configuration, for replies, Generated_Intents, summaries and Conclusion drafts.
2. THE Backend_API SHALL read provider credentials only from the environment or the provider's own credential store. It SHALL never write them to the Store, logs or responses.
3. IF no credentials are available, THEN THE Backend_API SHALL still start and serve existing Trees, and reply requests SHALL fail with a `provider_unavailable` error that says how to configure credentials.
4. WHERE the fake provider is configured, THE Backend_API SHALL produce deterministic replies without contacting any external service (used by tests and for offline development).
5. THE default test suite SHALL make no calls to a real LLM provider and SHALL fail any test that attempts one. Tests that call a real provider SHALL be opt-in, SHALL be run only with the owner's go-ahead, and SHALL cost no more than a few cents per run (owner's decision, 11 Oct 2026).
