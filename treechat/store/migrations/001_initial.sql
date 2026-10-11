-- Initial schema (design.md, Data Models). Migrations only ever add things (CLAUDE.md, Conventions).
-- Every rule the database can enforce itself is enforced here, so a bug elsewhere cannot rewrite history.

CREATE TABLE trees (
  id TEXT PRIMARY KEY,
  title TEXT CHECK (title IS NULL OR length(trim(title)) BETWEEN 1 AND 200),             -- Req 1.4
  trunk_branch_id TEXT NOT NULL REFERENCES branches(id) DEFERRABLE INITIALLY DEFERRED,
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL
);

CREATE TABLE branches (
  id TEXT PRIMARY KEY,
  tree_id TEXT NOT NULL REFERENCES trees(id) DEFERRABLE INITIALLY DEFERRED,
  parent_branch_id TEXT REFERENCES branches(id),
  kind TEXT NOT NULL CHECK (kind IN ('trunk', 'tangent', 'alternative')),
  anchor_message_id TEXT REFERENCES messages(id),
  anchor_start INTEGER,
  anchor_end INTEGER,
  anchor_quote TEXT,
  fork_point_message_id TEXT REFERENCES messages(id),
  intent TEXT CHECK (intent IS NULL OR length(intent) <= 200),                           -- Req 4.3
  status TEXT NOT NULL CHECK (status IN ('parked', 'open', 'closed')),
  framing_text TEXT,
  created_at TEXT NOT NULL,
  CHECK ((kind = 'trunk') = (parent_branch_id IS NULL)),                                 -- Req 6.1
  CHECK ((kind = 'trunk') = (anchor_message_id IS NULL)),                                -- Req 6.1
  CHECK (kind != 'trunk' OR (status = 'open' AND fork_point_message_id IS NULL)),        -- Req 10.1
  CHECK (kind = 'tangent' OR framing_text IS NULL),                                      -- Req 3.5
  CHECK (kind != 'tangent' OR parent_branch_id IS NOT NULL),
  CHECK (anchor_message_id IS NULL
         OR (anchor_start >= 0 AND anchor_start < anchor_end AND anchor_quote IS NOT NULL))  -- Req 4.5
);
CREATE UNIQUE INDEX one_trunk_per_tree ON branches(tree_id) WHERE parent_branch_id IS NULL;
CREATE INDEX branches_by_parent ON branches(parent_branch_id);
CREATE INDEX branches_by_tree ON branches(tree_id);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  tree_id TEXT NOT NULL REFERENCES trees(id) DEFERRABLE INITIALLY DEFERRED,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  parent_message_id TEXT REFERENCES messages(id),
  seq INTEGER NOT NULL CHECK (seq >= 0),
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'note')),
  content TEXT NOT NULL CHECK (length(trim(content)) >= 1),
  provider_blocks TEXT,
  model TEXT,
  stop_reason TEXT,
  manifest TEXT,
  source_branch_id TEXT REFERENCES branches(id),
  created_at TEXT NOT NULL,
  UNIQUE (branch_id, seq),                                                               -- Req 6.2
  CHECK (role = 'assistant'
         OR (provider_blocks IS NULL AND model IS NULL AND stop_reason IS NULL AND manifest IS NULL)),
  CHECK (role != 'assistant' OR (provider_blocks IS NOT NULL AND model IS NOT NULL AND manifest IS NOT NULL)),  -- Req 7.7
  CHECK ((role = 'note') = (source_branch_id IS NOT NULL))
);
CREATE INDEX messages_by_tree ON messages(tree_id);

CREATE TABLE status_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  from_status TEXT CHECK (from_status IS NULL OR from_status IN ('parked', 'open', 'closed')),
  to_status TEXT NOT NULL CHECK (to_status IN ('parked', 'open', 'closed')),
  at TEXT NOT NULL
);
CREATE INDEX status_events_by_branch ON status_events(branch_id, id);

CREATE TABLE closings (
  id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  outcome TEXT NOT NULL CHECK (outcome IN ('merged', 'kept', 'abandoned')),
  conclusion TEXT CHECK (conclusion IS NULL OR length(conclusion) <= 2000),              -- Req 12.3
  merge_target_branch_id TEXT REFERENCES branches(id),
  note_message_id TEXT REFERENCES messages(id),
  closed_at TEXT NOT NULL,
  CHECK (outcome != 'merged' OR (merge_target_branch_id IS NOT NULL AND note_message_id IS NOT NULL)),
  CHECK (outcome = 'merged' OR (merge_target_branch_id IS NULL AND note_message_id IS NULL)),
  CHECK (outcome = 'abandoned' OR (conclusion IS NOT NULL AND length(trim(conclusion)) >= 1))  -- Req 12.2
);
CREATE INDEX closings_by_branch ON closings(branch_id);

CREATE TABLE generated_texts (
  id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  kind TEXT NOT NULL CHECK (kind IN ('intent', 'standing')),
  text TEXT NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX generated_texts_by_branch ON generated_texts(branch_id, kind, created_at);

-- Append-only tables (Req 3.1, 16.4): no UPDATE, no DELETE, ever.
CREATE TRIGGER messages_no_update BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are immutable'); END;
CREATE TRIGGER messages_no_delete BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'messages cannot be deleted'); END;
CREATE TRIGGER status_events_no_update BEFORE UPDATE ON status_events
BEGIN SELECT RAISE(ABORT, 'status_events are append-only'); END;
CREATE TRIGGER status_events_no_delete BEFORE DELETE ON status_events
BEGIN SELECT RAISE(ABORT, 'status_events cannot be deleted'); END;
CREATE TRIGGER closings_no_update BEFORE UPDATE ON closings
BEGIN SELECT RAISE(ABORT, 'closings are append-only'); END;
CREATE TRIGGER closings_no_delete BEFORE DELETE ON closings
BEGIN SELECT RAISE(ABORT, 'closings cannot be deleted'); END;
CREATE TRIGGER generated_texts_no_update BEFORE UPDATE ON generated_texts
BEGIN SELECT RAISE(ABORT, 'generated_texts are append-only'); END;
CREATE TRIGGER generated_texts_no_delete BEFORE DELETE ON generated_texts
BEGIN SELECT RAISE(ABORT, 'generated_texts cannot be deleted'); END;
-- No deletion of Trees or Branches in v1 (Req 16.3).
CREATE TRIGGER branches_no_delete BEFORE DELETE ON branches
BEGIN SELECT RAISE(ABORT, 'branches cannot be deleted'); END;
CREATE TRIGGER trees_no_delete BEFORE DELETE ON trees
BEGIN SELECT RAISE(ABORT, 'trees cannot be deleted'); END;

-- Messages: one chain per Branch, never into a closed Branch (Req 6.2, 12.8).
CREATE TRIGGER messages_closed_branch BEFORE INSERT ON messages
WHEN (SELECT status FROM branches WHERE id = NEW.branch_id) = 'closed'
BEGIN SELECT RAISE(ABORT, 'a closed branch accepts no messages'); END;
CREATE TRIGGER messages_same_tree BEFORE INSERT ON messages
WHEN NEW.tree_id IS NOT (SELECT tree_id FROM branches WHERE id = NEW.branch_id)
BEGIN SELECT RAISE(ABORT, 'message and branch are in different trees'); END;
CREATE TRIGGER messages_chain_first BEFORE INSERT ON messages
WHEN NEW.seq = 0
 AND NEW.parent_message_id IS NOT (SELECT fork_point_message_id FROM branches WHERE id = NEW.branch_id)
BEGIN SELECT RAISE(ABORT, 'the first message must follow the fork point'); END;
CREATE TRIGGER messages_chain_next BEFORE INSERT ON messages
WHEN NEW.seq > 0
 AND NEW.parent_message_id IS NOT (SELECT id FROM messages WHERE branch_id = NEW.branch_id AND seq = NEW.seq - 1)
BEGIN SELECT RAISE(ABORT, 'a message must follow the previous message of its branch'); END;

-- Branches: a strict tree, with the once-set facts frozen (Req 4.4, 6.1, 7.3, 9.3).
CREATE TRIGGER branches_same_tree_parent BEFORE INSERT ON branches
WHEN NEW.parent_branch_id IS NOT NULL
 AND (SELECT tree_id FROM branches WHERE id = NEW.parent_branch_id) IS NOT NEW.tree_id
BEGIN SELECT RAISE(ABORT, 'parent branch is in a different tree'); END;
CREATE TRIGGER branches_anchor_in_parent BEFORE INSERT ON branches
WHEN NEW.anchor_message_id IS NOT NULL
 AND (SELECT branch_id FROM messages WHERE id = NEW.anchor_message_id) IS NOT NEW.parent_branch_id
BEGIN SELECT RAISE(ABORT, 'the anchor message must belong to the parent branch'); END;
CREATE TRIGGER branches_frozen_facts BEFORE UPDATE ON branches
WHEN OLD.id IS NOT NEW.id OR OLD.tree_id IS NOT NEW.tree_id OR OLD.parent_branch_id IS NOT NEW.parent_branch_id
  OR OLD.kind IS NOT NEW.kind OR OLD.anchor_message_id IS NOT NEW.anchor_message_id
  OR OLD.anchor_start IS NOT NEW.anchor_start OR OLD.anchor_end IS NOT NEW.anchor_end
  OR OLD.anchor_quote IS NOT NEW.anchor_quote OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT, 'a branch''s parent, kind and anchor never change'); END;
CREATE TRIGGER branches_framing_once BEFORE UPDATE ON branches
WHEN OLD.framing_text IS NOT NULL AND OLD.framing_text IS NOT NEW.framing_text
BEGIN SELECT RAISE(ABORT, 'the framing block is fixed once set'); END;
CREATE TRIGGER branches_fork_point_before_first_message BEFORE UPDATE ON branches
WHEN OLD.fork_point_message_id IS NOT NEW.fork_point_message_id
 AND EXISTS (SELECT 1 FROM messages WHERE branch_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'the fork point cannot move once the branch has messages'); END;
