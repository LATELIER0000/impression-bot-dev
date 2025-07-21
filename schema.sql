-- schema.sql
DROP TABLE IF EXISTS history;
DROP TABLE IF EXISTS users;

-- NOUVEAU : Table pour les utilisateurs
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL
);

-- MODIFIÉ : La table history est maintenant liée aux utilisateurs
CREATE TABLE history (
  task_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  -- La colonne 'username' remplace 'client_name' et fait référence à un utilisateur
  username TEXT NOT NULL,
  timestamp TEXT NOT NULL,
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
  original_path TEXT
);
