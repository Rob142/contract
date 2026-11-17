ALTER TABLE users ADD COLUMN preferred_mode text NOT NULL DEFAULT 'freelancer' CHECK (preferred_mode IN ('freelancer','client'));
CREATE TABLE workspaces (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE workspace_members (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
 UNIQUE(workspace_id,user_id)
);
CREATE TABLE client_project_links (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL UNIQUE REFERENCES projects ON DELETE CASCADE,
 workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
 approver_id uuid REFERENCES users, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE client_project_members (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), link_id uuid NOT NULL REFERENCES client_project_links ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE, can_finance boolean NOT NULL DEFAULT false,
 UNIQUE(link_id,user_id)
);
CREATE TABLE client_invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), creator_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
 workspace_id uuid REFERENCES workspaces ON DELETE CASCADE, project_id uuid REFERENCES projects ON DELETE CASCADE,
 email text NOT NULL, role text NOT NULL CHECK(role IN ('admin','member','viewer')),
 token_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
 used_at timestamptz, revoked_at timestamptz, mail_status text NOT NULL DEFAULT 'not_sent',
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((workspace_id IS NULL) <> (project_id IS NULL))
);
CREATE TABLE client_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects ON DELETE CASCADE,
 title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE client_delivery_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), delivery_id uuid NOT NULL REFERENCES client_deliveries ON DELETE CASCADE,
 seq integer NOT NULL, payload jsonb NOT NULL, due_date date,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(delivery_id,seq)
);
CREATE TABLE client_review_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), version_id uuid NOT NULL REFERENCES client_delivery_versions ON DELETE CASCADE,
 actor_id uuid NOT NULL REFERENCES users, actor_name text NOT NULL, workspace_name text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('comment','seen','changes','approved')),
 body text NOT NULL DEFAULT '', revision_request_id uuid REFERENCES revision_requests,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX client_one_decision ON client_review_events(version_id) WHERE kind IN ('changes','approved');
CREATE TABLE freelancer_profiles (
 id uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE, published boolean NOT NULL DEFAULT false,
 payload jsonb NOT NULL DEFAULT '{}', updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE client_inquiries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces ON DELETE CASCADE,
 creator_id uuid NOT NULL REFERENCES users, freelancer_id uuid NOT NULL REFERENCES users,
 payload jsonb NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent','negotiating','quoted','contracted')),
 project_id uuid REFERENCES projects, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE client_quote_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), inquiry_id uuid NOT NULL REFERENCES client_inquiries ON DELETE CASCADE,
 seq integer NOT NULL, payload jsonb NOT NULL, accepted_at timestamptz,
 accepted_by uuid REFERENCES users, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(inquiry_id,seq)
);
CREATE TABLE client_inquiry_messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), inquiry_id uuid NOT NULL REFERENCES client_inquiries ON DELETE CASCADE,
 actor_id uuid NOT NULL REFERENCES users, actor_name text NOT NULL, body text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE client_extra_acceptances (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), quote_id uuid NOT NULL UNIQUE REFERENCES extra_quotes ON DELETE CASCADE,
 actor_id uuid NOT NULL REFERENCES users, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE tasks ADD COLUMN client_visible boolean NOT NULL DEFAULT false;
