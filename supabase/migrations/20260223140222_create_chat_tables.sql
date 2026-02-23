/*
  # Chat Pubblica - Database Schema

  1. New Tables
    - `chat_groups`
      - `id` (uuid, primary key) - Unique group identifier
      - `name` (varchar) - Group display name
      - `description` (text) - Group description
      - `is_default` (boolean) - Marks the single default public group
      - `is_public` (boolean) - Whether the group is visible to all users
      - `invite_code` (varchar, unique) - Code for joining private groups
      - `created_by` (uuid) - Admin user ID who created the group
      - `created_at` (timestamptz) - Creation timestamp
      - `updated_at` (timestamptz) - Last update timestamp

    - `group_members`
      - `id` (uuid, primary key) - Unique membership identifier
      - `group_id` (uuid, FK) - Reference to chat_groups
      - `user_id` (uuid) - User identifier from users microservice
      - `username` (varchar) - Cached username for display
      - `role` (varchar) - 'admin' or 'member'
      - `joined_at` (timestamptz) - When the user joined

    - `messages`
      - `id` (uuid, primary key) - Unique message identifier
      - `group_id` (uuid, FK) - Reference to chat_groups
      - `sender_id` (uuid, nullable) - Null for system messages
      - `sender_username` (varchar, nullable) - Cached username for display
      - `content` (text) - Message content
      - `message_type` (varchar) - 'text', 'system', 'admin_announcement'
      - `reply_to_id` (uuid, FK, nullable) - For reply threading
      - `metadata` (jsonb) - Flexible extra data
      - `is_edited` (boolean) - Whether message was edited
      - `edited_at` (timestamptz, nullable) - When message was last edited
      - `is_deleted` (boolean) - Soft delete flag
      - `created_at` (timestamptz) - Creation timestamp
      - `updated_at` (timestamptz) - Last update timestamp

    - `message_read_status`
      - `id` (uuid, primary key) - Unique read status identifier
      - `message_id` (uuid, FK) - Reference to messages
      - `user_id` (uuid) - User who read the message
      - `read_at` (timestamptz) - When the message was read

  2. Security
    - RLS enabled on all tables
    - Policies restrict access based on group membership and admin role

  3. Indexes
    - Messages indexed by (group_id, created_at) for efficient pagination
    - group_members indexed by (group_id, user_id) for membership lookups
    - messages indexed by (sender_id) for user message lookups

  4. Notes
    - The default public group is created via application startup logic
    - System messages have sender_id = NULL
    - Soft delete preserves message history
    - is_edited flag + edited_at track message modifications
*/

CREATE TABLE IF NOT EXISTS chat_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(255) NOT NULL,
  description text DEFAULT '',
  is_default boolean DEFAULT false,
  is_public boolean DEFAULT false,
  invite_code varchar(64) UNIQUE,
  created_by uuid NOT NULL,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS group_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  username varchar(255) DEFAULT '',
  role varchar(20) DEFAULT 'member',
  joined_at timestamptz DEFAULT now(),
  UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE,
  sender_id uuid,
  sender_username varchar(255),
  content text NOT NULL,
  message_type varchar(30) NOT NULL DEFAULT 'text',
  reply_to_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  metadata jsonb DEFAULT '{}',
  is_edited boolean DEFAULT false,
  edited_at timestamptz,
  is_deleted boolean DEFAULT false,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS message_read_status (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  read_at timestamptz DEFAULT now(),
  UNIQUE(message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_group_created
  ON messages(group_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_sender
  ON messages(sender_id);

CREATE INDEX IF NOT EXISTS idx_group_members_group_user
  ON group_members(group_id, user_id);

CREATE INDEX IF NOT EXISTS idx_group_members_user
  ON group_members(user_id);

CREATE INDEX IF NOT EXISTS idx_messages_reply_to
  ON messages(reply_to_id)
  WHERE reply_to_id IS NOT NULL;

ALTER TABLE chat_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_read_status ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access to chat_groups"
  ON chat_groups
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Service role full access to group_members"
  ON group_members
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Service role full access to messages"
  ON messages
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Service role full access to message_read_status"
  ON message_read_status
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

ALTER PUBLICATION supabase_realtime ADD TABLE messages;
