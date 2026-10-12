-- Req 9: Branch_Summaries, the model-written names of graph nodes. Added; nothing earlier changes (Req 7.2).
-- Keyed by the Branch's first Message, which starts a Branch for ever (design.md, Branch summaries: key).

CREATE TABLE branch_summaries (
  message_id TEXT PRIMARY KEY REFERENCES messages(id),
  summary TEXT NOT NULL CHECK (length(summary) BETWEEN 1 AND 60),
  model TEXT NOT NULL,
  source TEXT NOT NULL,                     -- JSON array of the Summary_Source ids, oldest first (Req 9.3)
  prompt_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

-- A Branch starts at a user Message (the Root, or a child of a Fork).
CREATE TRIGGER branch_summaries_shape BEFORE INSERT ON branch_summaries
WHEN (SELECT role FROM messages WHERE id = NEW.message_id) IS NOT 'user'
BEGIN SELECT RAISE(ABORT, 'a summary names a branch, which starts at a user message'); END;

-- Req 9.3: a persisted Branch_Summary never changes and is never deleted.
CREATE TRIGGER branch_summaries_no_update BEFORE UPDATE ON branch_summaries
BEGIN SELECT RAISE(ABORT, 'summaries are immutable'); END;

CREATE TRIGGER branch_summaries_no_delete BEFORE DELETE ON branch_summaries
BEGIN SELECT RAISE(ABORT, 'summaries are never deleted'); END;
