-- init_db.sql : crée les tables et insère des données de démonstration

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Business settings
INSERT OR REPLACE INTO settings(key,value) VALUES('TAX_RATE','0.19'); -- 19% TVA
INSERT OR REPLACE INTO settings(key,value) VALUES('REMISE_MANAGER_THRESHOLD_PERCENT','0.10'); -- 10%
INSERT OR REPLACE INTO settings(key,value) VALUES('REMISE_MANAGER_THRESHOLD_AMOUNT','50.0'); -- 50 (DT)

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0,
    vat REAL NOT NULL DEFAULT 0.19
);

CREATE TABLE IF NOT EXISTS carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'OPEN', -- OPEN, CHECKOUT_PENDING, PAID, CANCELLED
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    qty INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    discount REAL NOT NULL DEFAULT 0.0, -- montant discount sur la ligne (appliqué before tax)
    FOREIGN KEY(cart_id) REFERENCES carts(id) ON DELETE CASCADE,
    FOREIGN KEY(article_id) REFERENCES articles(id)
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL,
    total_ht REAL NOT NULL,
    total_tax REAL NOT NULL,
    total_ttc REAL NOT NULL,
    payment_method TEXT,
    payment_status TEXT DEFAULT 'PENDING', -- PENDING, AUTHORIZED, FAILED
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(cart_id) REFERENCES carts(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    payload TEXT,
    actor TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- seed sample articles
INSERT OR IGNORE INTO articles(sku,name,price,stock,reserved,vat) VALUES('SKU-001','Chemise Bleu',70.0,10,0,0.19);
INSERT OR IGNORE INTO articles(sku,name,price,stock,reserved,vat) VALUES('SKU-002','Jeans Slim',120.0,5,0,0.19);
INSERT OR IGNORE INTO articles(sku,name,price,stock,reserved,vat) VALUES('SKU-003','Chaussures Sport',200.0,4,0,0.19);
INSERT OR IGNORE INTO articles(sku,name,price,stock,reserved,vat) VALUES('SKU-004','Ceinture Cuir',35.0,15,0,0.19);
