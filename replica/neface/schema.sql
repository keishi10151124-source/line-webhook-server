-- face-swap schema for Postgres, generated from face_swap/app/models.py (the source of truth).
-- Access rule: every query goes through the data layer's owner check (no RLS).
-- Only the owner's own face: camera + liveness, plus uploaded photos that matched it.

CREATE TABLE purges (
	id VARCHAR(36) NOT NULL, 
	key VARCHAR(512) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE faces (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	liveness_challenge_id VARCHAR(64) NOT NULL, 
	liveness_passed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	age_check_passed BOOLEAN NOT NULL, 
	embedding BYTEA NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT face_camera_only CHECK (source = 'camera'), 
	CONSTRAINT face_age_check CHECK (age_check_passed), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (liveness_challenge_id)
);

CREATE TABLE liveness_challenges (
	id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	steps JSON NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_liveness_challenges_user_id ON liveness_challenges (user_id);

CREATE TABLE source_videos (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	original_name VARCHAR(255) NOT NULL, 
	video_key VARCHAR(512) NOT NULL, 
	bytes BIGINT NOT NULL, 
	duration_s NUMERIC(7, 2), 
	width INTEGER, 
	height INTEGER, 
	rights_confirmed BOOLEAN NOT NULL, 
	rights_note TEXT, 
	detected_faces JSON NOT NULL, 
	analysis_status VARCHAR(16) NOT NULL, 
	analysis_error TEXT, 
	safety_status VARCHAR(16) NOT NULL, 
	safety_result JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT video_kind CHECK (kind in ('template','upload')), 
	CONSTRAINT video_rights_confirmed CHECK (rights_confirmed), 
	CONSTRAINT video_bytes_positive CHECK (bytes > 0), 
	CONSTRAINT video_analysis_status CHECK (analysis_status in ('pending','analyzing','done','failed')), 
	CONSTRAINT video_safety_status CHECK (safety_status in ('pending','passed','blocked')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_source_videos_user_created ON source_videos (user_id, created_at);
CREATE INDEX ix_source_videos_analysis_status ON source_videos (analysis_status);

CREATE TABLE face_photos (
	id VARCHAR(36) NOT NULL, 
	face_id VARCHAR(36) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	image_key VARCHAR(512) NOT NULL, 
	match_score FLOAT, 
	match_threshold FLOAT NOT NULL, 
	safety_status VARCHAR(16) NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT photo_source CHECK (source in ('camera','upload')), 
	CONSTRAINT upload_must_match_camera_face CHECK (source = 'camera' or (match_score is not null and match_score >= match_threshold)), 
	CONSTRAINT photo_safety_passed CHECK (safety_status = 'passed'), 
	FOREIGN KEY(face_id) REFERENCES faces (id) ON DELETE CASCADE
);

CREATE INDEX ix_face_photos_face_id ON face_photos (face_id);

CREATE TABLE templates (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	source_video_id VARCHAR(36) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	category VARCHAR(60), 
	license_note TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (source_video_id), 
	FOREIGN KEY(source_video_id) REFERENCES source_videos (id) ON DELETE CASCADE
);

CREATE INDEX ix_templates_user_id ON templates (user_id);

CREATE TABLE swap_jobs (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	source_video_id VARCHAR(36) NOT NULL, 
	face_photo_id VARCHAR(36), 
	target_face_index INTEGER NOT NULL, 
	aspect VARCHAR(8) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	provider_task_id VARCHAR(128), 
	provider_price BIGINT, 
	safety_status VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	attempts INTEGER NOT NULL, 
	error TEXT, 
	estimated_seconds NUMERIC(7, 2), 
	estimated_cost_micro_usd BIGINT, 
	locked_at TIMESTAMP WITH TIME ZONE, 
	next_poll_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT job_aspect CHECK (aspect in ('9:16','16:9')), 
	CONSTRAINT job_target_index CHECK (target_face_index >= 0), 
	CONSTRAINT job_safety_status CHECK (safety_status in ('pending','passed','blocked')), 
	CONSTRAINT job_status CHECK (status in ('queued','submitted','processing','postprocessing','done','failed','blocked','cancelled')), 
	CONSTRAINT safety_before_submit CHECK (status in ('queued','failed','blocked','cancelled') or safety_status = 'passed'), 
	CONSTRAINT face_required_to_run CHECK (status in ('queued','done','failed','blocked','cancelled') or face_photo_id is not null), 
	CONSTRAINT job_idempotency UNIQUE (user_id, idempotency_key), 
	CONSTRAINT job_provider_task UNIQUE (provider, provider_task_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_video_id) REFERENCES source_videos (id) ON DELETE CASCADE, 
	FOREIGN KEY(face_photo_id) REFERENCES face_photos (id) ON DELETE SET NULL
);

CREATE INDEX ix_swap_jobs_status_poll ON swap_jobs (status, next_poll_at);
CREATE INDEX ix_swap_jobs_source_video_id ON swap_jobs (source_video_id);
CREATE INDEX ix_swap_jobs_face_photo_id ON swap_jobs (face_photo_id);
CREATE INDEX ix_swap_jobs_user_created ON swap_jobs (user_id, created_at);

CREATE TABLE outputs (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	video_key VARCHAR(512) NOT NULL, 
	aspect VARCHAR(8) NOT NULL, 
	height INTEGER NOT NULL, 
	watermarked BOOLEAN NOT NULL, 
	c2pa_signed BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT output_aspect CHECK (aspect in ('9:16','16:9')), 
	CONSTRAINT output_hd CHECK (height >= 720), 
	CONSTRAINT output_watermarked CHECK (watermarked), 
	CONSTRAINT output_c2pa_signed CHECK (c2pa_signed), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (job_id), 
	FOREIGN KEY(job_id) REFERENCES swap_jobs (id) ON DELETE CASCADE
);

CREATE INDEX ix_outputs_user_created ON outputs (user_id, created_at);

CREATE TABLE usage_events (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36), 
	service VARCHAR(16) NOT NULL, 
	units NUMERIC NOT NULL, 
	unit VARCHAR(16) NOT NULL, 
	cost_micro_usd BIGINT NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT usage_service CHECK (service in ('faceswap','claude','storage')), 
	CONSTRAINT usage_cost_positive CHECK (cost_micro_usd >= 0), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES swap_jobs (id) ON DELETE SET NULL
);

CREATE INDEX ix_usage_events_job_id ON usage_events (job_id);
CREATE INDEX ix_usage_user_created ON usage_events (user_id, created_at);

