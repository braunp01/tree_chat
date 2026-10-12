# Requirements Document

> **Status: v2, open questions answered by the owner 12 Oct 2026.** Replaces the v1 requirements (passage tangents, parking, closing and
> merging), which the owner withdrew on 12 Oct 2026. v1 is in git history (`main` at 1e59794).

## Introduction

Tree Chat is a local chat client for one person talking to an LLM. It looks and works like an ordinary
chat: the conversation up to where you are, the latest reply, and one box to type in.

The difference is that a conversation is a tree, and all conversations together are a forest. At any time you can go back to an earlier reply and ask
something else. That adds a new child at that point and leaves everything that was already there
untouched. A graph of the tree sits beside the chat, so you can always see where you are and jump to
any branch in one click.

There are only two actions: **navigate** to a point, and **send** from it. Nothing is ever edited,
regenerated or deleted.

What the model receives for a reply is exactly the conversation on screen: the path from the start of
the Tree to that point. A branch never sees what was added to other branches, including later messages
on its ancestors. What was sent for every reply is recorded exactly and can be inspected.

Differences from an ordinary chat with edit-branching are deliberate and limited to the experience:
the whole tree is visible, any point is one click away, and branching is its own action rather than an
edit.

In scope: one user, one machine, one LLM provider, many Trees.

Out of scope (owner, 12 Oct 2026): multiple users, sign-in, sync, mobile layout, editing, regenerating,
deleting, selecting a passage to branch from, parking or queueing branches, closing branches, merging
results back into an ancestor, and any context other than the path.

## Glossary

- **Forest**: all Trees. The Trees menu lists them.
- **Tree**: one whole conversation: a tree of Messages with exactly one Root.
- **Message**: an immutable unit of conversation with role `user` or `assistant`. Every Message except the
  Root has one parent Message. A user Message's parent is an assistant Message; an
  assistant Message's parent is a user Message.
- **Reply**: the assistant Message whose parent is a given user Message. A user Message has at most one.
- **Root**: the first Message the user typed when creating the Tree; the only Message with no parent.
- **Current_Point**: where the user is: normally an assistant Message; a question still waiting for its Reply
  can be shown too, but nothing is sent from it (Req 3.10). The chat shows the Path to it.
- **Path**: the Messages from the Root down to a given Message, in order.
- **Leaf**: a Message with no children.
- **Fork**: an assistant Message with more than one child.
- **Branch**: a run of Messages drawn as one node of the Branch_Graph. It starts at the Root or at a child of a
  Fork and continues down through single children until a Fork or a Leaf.
  Branches are derived from the Messages; they are not stored.
- **Context**: everything sent to the model for one Reply.
- **Context_Manifest**: the exact, ordered record of a Context (Message ids, model and generation
  settings), stored with every assistant Message.
- **Branch_Graph**: the node-link picture of a Tree's Branches beside the chat.
- **Backend_API**: the local HTTP server. It is the authority on every rule below.
- **Front_End**: the browser interface. A limit enforced only there is a convenience.
- **Store**: the local database file.

## Requirements

### Requirement 1: Trees

**User Story:** As the user, I want separate conversations, so that unrelated topics do not share a tree.

#### Acceptance Criteria

1. WHEN the user sends a Message from "New tree", THE Backend_API SHALL create a Tree with that Message as its Root, in one transaction, and return both. No empty Tree exists (owner, 12 Oct 2026: the forest's trees each have one root, the first message typed).
2. THE Front_End SHALL list Trees in a menu reachable from every view, most recently active first, with each Tree's title.
3. WHEN a Tree is created, THE Backend_API SHALL set its title to the first 60 characters of the Root. The user may rename a Tree at any time.
4. IF a title is empty or longer than 200 characters after trimming, THEN THE Backend_API SHALL reject it without persisting anything and return a validation error naming the `title` field.

### Requirement 2: The chat

**User Story:** As the user, I want the screen to look like an ordinary chat, so that the tree never gets
in the way of talking.

#### Acceptance Criteria

1. THE Front_End SHALL show the Path to the Current_Point as one continuous chat, oldest first, with the composer below it. Nothing on the Path is collapsed.
2. WHEN the user opens a Tree, THE Front_End SHALL set the Current_Point to the most recently created Reply (or the Root while its Reply is pending) and show the latest Message.
3. WHEN the user chooses "go back to here" on an assistant Message in the chat, THE Front_End SHALL make it the Current_Point: the chat shows the Path to it and nothing after it. Navigating SHALL create nothing.
4. WHILE the Current_Point already has children, THE Front_End SHALL say above the composer that sending will start a new branch from here, and offer to jump to the latest Message below it.
5. THE Front_End SHALL show per-Message actions ("go back to here", "see what was sent") only on hover or focus.
6. THE Front_End SHALL render assistant Messages as markdown and user Messages as typed.

### Requirement 3: Sending and replies

**User Story:** As the user, I want to send from wherever I am and see the reply as it is written, so that
branching is just talking.

#### Acceptance Criteria

1. WHEN the user sends a non-empty Message in a Tree, THE Backend_API SHALL persist it as a new child of the Current_Point before any model call is made. There is one Send action. Starting from a blank page is "New tree" (Req 1.1).
2. IF the Current_Point given is not an assistant Message of that Tree, THEN THE Backend_API SHALL reject the send with a `conflict` error.
3. WHEN a user Message has no Reply and a reply is requested, THE Backend_API SHALL assemble the Context (Req 4), call the model, stream the reply text as it arrives, and persist the complete Reply with its Context_Manifest when the model finishes.
4. WHEN the user sends, THE Front_End SHALL request the Reply at once and make the new Reply the Current_Point when it is saved.
5. IF the model call fails or is refused, THEN THE Backend_API SHALL persist no Reply, keep the user Message, report the error category, and allow the Reply to be requested again.
6. IF the model stops at its output limit, THEN THE Backend_API SHALL persist the Reply, and THE Front_End SHALL mark it as cut off.
7. WHILE a Reply is being generated for a user Message, THE Backend_API SHALL reject a second reply request for it with a `busy` error. Replies for other Messages are unaffected.
8. WHEN the Front_End disconnects during generation, THE Backend_API SHALL finish and persist the Reply anyway; reopening shows it, or shows it still in progress.
9. IF Message content is empty after trimming or longer than 100,000 characters, THEN THE Backend_API SHALL reject it without persisting anything and return a validation error naming the `content` field.
10. A user Message without a Reply is a Leaf the user can see, with a control to request the Reply again. It cannot be the Current_Point for sending.

### Requirement 4: What the model sees

**User Story:** As the user, I want each reply to be based on exactly the conversation I see, and to be able
to check what was sent, so that I can trust it.

#### Acceptance Criteria

1. THE Backend_API SHALL build the Context for a Reply from the Path to its user Message, in order, and nothing else.
2. THE Backend_API SHALL make Context assembly deterministic: the same Store contents and settings always give byte-identical model requests.
3. THE Backend_API SHALL render the Contexts of two Replies whose Paths share a prefix byte-identically through that prefix, so the provider's prompt cache can be reused.
4. WHEN a Reply is persisted, THE Store SHALL persist its Context_Manifest with it: the ordered Message ids sent, the model id and the generation settings.
5. WHEN the user asks to see what was sent for a Reply, THE Front_End SHALL show its Context_Manifest as the list of Messages sent, in order.
6. IF an assembled Context exceeds the model's input limit, THEN THE Backend_API SHALL persist nothing and return a `context_too_large` error.

### Requirement 5: Immutability

**User Story:** As the user, I want nothing I or the model wrote ever to change or vanish, so that every
branch stays exactly as it was.

#### Acceptance Criteria

1. THE Store SHALL never change or delete a persisted Message or Context_Manifest; an attempt SHALL fail.
2. THE Backend_API SHALL offer no editing, regenerating or deleting of Messages, and no deleting of Trees.
3. THE Store SHALL keep the shape rules whatever the application does: each Tree has exactly one Root, every other user Message's parent is an assistant Message, an assistant Message's parent is a user Message, a user Message has at most one Reply, and a parent belongs to the same Tree.

### Requirement 6: The Branch_Graph

**User Story:** As the user, I want to see the tree beside the chat, with my position marked, so that I
know where I am and can jump to any branch in one click.

#### Acceptance Criteria

1. THE Front_End SHALL show the Branch_Graph of the current Tree beside the chat at all times: one node per Branch, an edge from each Branch to the Branches that fork from its end, the Root's Branch at the left and depth increasing to the right.
2. THE Front_End SHALL label each node with the start of its first user Message and its Message count, and SHALL highlight the Branch holding the Current_Point and the edges on the Path to it.
3. THE Branch_Graph SHALL always draw: the Branches on the Path to the Current_Point, their sibling Branches, and the Branches that fork from the current one. Below any other Branch, its descendants are hidden in one collapsed node that says how many Branches it holds.
4. WHEN the user activates a collapsed node, or the toggle on a node, THE Branch_Graph SHALL expand or collapse it. THE Front_End SHALL keep that choice while the user stays in the Tree. What Req 6.3 requires cannot be collapsed.
5. WHEN the user activates a node, THE Front_End SHALL make the last Message of that Branch the Current_Point (Req 2.3). If that is a question still waiting for its Reply, the chat shows it with the control to request the Reply (Req 3.10) and the composer stays off until it is answered.
6. THE Branch_Graph SHALL order sibling Branches by creation time, so adding a Branch never reorders existing ones.
7. WHEN the Current_Point changes, THE Branch_Graph SHALL scroll so that its node is in view.
8. WHEN the user hovers or focuses a node, THE Front_End SHALL show its full label and the Message it forked from.
9. THE Branch_Graph SHALL pan (drag, or Shift and the arrow keys), zoom (wheel, pinch, `+`, `-`) and fit (a button, or `0`). WHEN the user presses `M`, THE Front_End SHALL enlarge it to fill the window and restore it on `M` or Escape; activating a node in the enlarged graph navigates and restores it.
10. THE Branch_Graph SHALL be operable from the keyboard (up and down between siblings, left to the parent, right to the first child, Enter to open, space to expand or collapse) and SHALL tell assistive technology each node's label, depth and place among its siblings.
11. THE Front_End SHALL stay responsive with 500 Branches and 10,000 Messages in one Tree: opening a Tree or moving the Current_Point completes within one second, and the graph pans and zooms at 30 frames per second or better on the owner's machine.

### Requirement 7: Local persistence

**User Story:** As the user, I want everything kept in one local file that survives restarts and upgrades.

#### Acceptance Criteria

1. THE Store SHALL keep all Trees, Messages and Context_Manifests in one local database file.
2. WHEN the Backend_API starts with a Store created by an earlier version of this design, it SHALL bring it up to date without losing data. This is safe to run on every start.
3. IF any write in an operation fails, THEN THE Store SHALL keep none of that operation's writes.

### Requirement 8: Model provider and secrets

**User Story:** As the user, I want to choose the model in one setting and keep my API key out of the
project.

#### Acceptance Criteria

1. THE Backend_API SHALL use one LLM provider, set in configuration, for every Reply.
2. THE Backend_API SHALL read provider credentials only from the environment or the provider's own credential store, and SHALL never write them to the Store, logs or responses.
3. IF no credentials are available, THEN THE Backend_API SHALL still start and serve existing Trees, and reply requests SHALL fail with a `provider_unavailable` error that says how to configure credentials.
4. WHERE the fake provider is configured, THE Backend_API SHALL produce deterministic replies without contacting any external service.
5. THE default test suite SHALL make no calls to a real LLM provider and SHALL fail any test that attempts one. Tests that call a real provider SHALL be opt-in, run only with the owner's go-ahead, and cost no more than a few cents per run.
