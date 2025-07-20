-- schema.sql
DROP TABLE IF EXISTS history;

CREATE TABLE history (
  task_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  client_name TEXT NOT NULL,
  file_name TEXT NOT NULL,
  secure_filename TEXT NOT NULL,
  status TEXT,
  pages INTEGER,
  copies INTEGER,
  color TEXT,
  duplex TEXT,
  price REAL,
  paper_size TEXT,
  page_mode TEXT,
  start_page TEXT,
  end_page TEXT,
  source TEXT DEFAULT 'upload', -- 'upload' ou 'email'
  email_subject TEXT,
  original_path TEXT -- Chemin vers le fichier d'origine avant conversion
);
