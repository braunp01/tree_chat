-- v2 schema (design.md, Data Model): a forest of Trees, each a tree of immutable Messages.
-- Every rule the database can enforce itself is enforced here, so a bug elsewhere cannot rewrite history (Req 5).
-- Migrations only ever add things.

CREATE TABLE trees (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),                     -- Req 1.4
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  tree_id TEXT NOT NULL REFERENCES trees(id),
  parent_id TEXT REFERENCES messages(id),
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL CHECK (length(trim(content)) >= 1),                             -- Req 3.9
  provider_blocks TEXT,
  model TEXT,
  stop_reason TEXT,
  manifest TEXT,
  created_at TEXT NOT NULL,
  CHECK (role = 'assistant'
         OR (provider_blocks IS NULL AND model IS NULL AND stop_reason IS NULL AND manifest IS NULL)),
  CHECK (role = 'user' OR (provider_blocks IS NOT NULL AND model IS NOT NULL AND manifest IS NOT NULL)),  -- Req 4.4
  CHECK (role = 'user' OR parent_id IS NOT NULL)                                          -- the Root is a user Message
);
CREATE UNIQUE INDEX one_root_per_tree ON messages(tree_id) WHERE parent_id IS NULL;               -- Req 5.3
CREATE UNIQUE INDEX one_reply_per_user_message ON messages(parent_id) WHERE role = 'assistant';   -- Req 5.3
CREATE INDEX messages_by_tree ON messages(tree_id, created_at);
CREATE INDEX messages_by_parent ON messages(parent_id);

-- Req 5.3: a parent is in the same Tree and has the other role (user -> assistant -> user ...).
CREATE TRIGGER messages_shape BEFORE INSERT ON messages
WHEN NEW.parent_id IS NOT NULL
 AND ((SELECT tree_id FROM messages WHERE id = NEW.parent_id) IS NOT NEW.tree_id
      OR (SELECT role FROM messages WHERE id = NEW.parent_id) IS NEW.role)
BEGIN SELECT RAISE(ABORT, 'a message must follow a message of the other role in the same tree'); END;

-- Req 5.1: Messages and manifests never change and are never deleted; nor are Trees.
CREATE TRIGGER messages_no_update BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are immutable'); END;

CREATE TRIGGER messages_no_delete BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are never deleted'); END;

CREATE TRIGGER trees_no_delete BEFORE DELETE ON trees
BEGIN SELECT RAISE(ABORT, 'trees are never deleted'); END;

CREATE TRIGGER trees_identity BEFORE UPDATE ON trees
WHEN OLD.id IS NOT NEW.id OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT, 'a tree''s id and creation time never change'); END;
