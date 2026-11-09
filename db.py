"""Conexion, esquema y datos iniciales (seed) de la base de datos SQLite.

El sistema de control de stock de Despensa Mora guarda:
  - proveedores
  - productos (con codigo de barras, precio, stock actual y stock minimo)
  - movimientos de stock (entradas y salidas)
  - lista de reposicion (faltantes / pedidos al proveedor)
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "stock.db"


def ean13_check_digit(prefix: str) -> str:
    """Calcula el digito verificador de un EAN-13 a partir de 12 digitos."""
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(prefix))
    return str((10 - total % 10) % 10)


def make_ean13(prefix: str) -> str:
    """Devuelve un EAN-13 valido de 13 digitos a partir de un prefijo de 12."""
    return prefix + ean13_check_digit(prefix)


def get_conn() -> sqlite3.Connection:
    """Abre una conexion a la base con filas accesibles por nombre de columna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS proveedores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL UNIQUE,
    contacto   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS productos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_barras TEXT NOT NULL UNIQUE,
    nombre        TEXT NOT NULL,
    categoria     TEXT DEFAULT '',
    precio        REAL NOT NULL DEFAULT 0,
    stock_actual  INTEGER NOT NULL DEFAULT 0,
    stock_minimo  INTEGER NOT NULL DEFAULT 0,
    proveedor_id  INTEGER REFERENCES proveedores(id)
);

CREATE TABLE IF NOT EXISTS movimientos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    tipo        TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida')),
    cantidad    INTEGER NOT NULL,
    motivo      TEXT DEFAULT '',
    fecha       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS lista_reposicion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id      INTEGER NOT NULL REFERENCES productos(id),
    cantidad_sugerida INTEGER NOT NULL DEFAULT 10,
    estado           TEXT NOT NULL DEFAULT 'anotado'
                     CHECK (estado IN ('anotado', 'pedido', 'recibido', 'reclamo')),
    fecha            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# Productos de ejemplo de la despensa (algunos por debajo del minimo y un
# faltante, para poder demostrar las alertas y el flujo del cursograma).
PRODUCTOS_SEED = [
    # (codigo 12 prefijo, nombre, categoria, precio, stock, minimo, proveedor)
    ("779000010001", "Arroz Gallo Oro 1kg", "Almacen", 2500, 40, 10, "Distribuidora El Sol"),
    ("779000010002", "Aceite Natura Girasol 1.5L", "Almacen", 4200, 12, 10, "Distribuidora El Sol"),
    ("779000010003", "Fideos Matarazzo Ñoquis 500g", "Almacen", 1800, 25, 8, "Distribuidora El Sol"),
    ("779000010004", "Harina Pureza 1kg", "Almacen", 1500, 6, 10, "Distribuidora El Sol"),
    ("779000010005", "Azúcar Ledesma 1kg", "Almacen", 1900, 30, 10, "Distribuidora El Sol"),
    ("779000010006", "Galletitas Águila Pitusas 170g", "Almacen", 1600, 22, 8, "Distribuidora El Sol"),
    ("779000010007", "Conserva de tomate Arcor 520g", "Almacen", 2100, 18, 6, "Distribuidora El Sol"),
    ("779000020001", "Yerba Rosamonte 1kg", "Bebidas", 4800, 15, 5, "Bebidas del Barrio"),
    ("779000020002", "Café Cabrales 250g", "Almacen", 3900, 0, 5, "Distribuidora El Sol"),
    ("779000020003", "Gaseosa Coca-Cola 2.25L", "Bebidas", 3500, 20, 8, "Bebidas del Barrio"),
    ("779000020004", "Agua Villavicencio 2L", "Bebidas", 1400, 3, 10, "Bebidas del Barrio"),
    ("779000020005", "Cerveza Quilmes Clásica 473ml", "Bebidas", 2100, 36, 12, "Bebidas del Barrio"),
    ("779000030001", "Leche La Serenísima Entera 1L", "Lácteos", 2300, 48, 12, "Lácteos San Miguel"),
    ("779000030002", "Queso cremoso La Serenísima 250g", "Lácteos", 3200, 10, 4, "Lácteos San Miguel"),
    ("779000030003", "Yogur Serenísimo 1L", "Lácteos", 2700, 8, 6, "Lácteos San Miguel"),
    ("779000040001", "Papel higiénico Higiénol 8u", "Limpieza", 5200, 9, 4, "Química Limpieza SRL"),
    ("779000040002", "Detergente Magistral 750ml", "Limpieza", 2900, 2, 8, "Química Limpieza SRL"),
    ("779000040003", "Jabón en polvo Ariel 800g", "Limpieza", 4500, 14, 5, "Química Limpieza SRL"),
]

PROVEEDORES_SEED = [
    ("Distribuidora El Sol", "ventas@elsol.com.ar · 11 5555-1111"),
    ("Bebidas del Barrio", "pedidos@bebidasdelbarrio.com · 11 5555-2222"),
    ("Lácteos San Miguel", "contacto@sanmiguel.com.ar · 11 5555-3333"),
    ("Química Limpieza SRL", "admin@quimicalimpieza.com · 11 5555-4444"),
]


def init_db() -> None:
    """Crea las tablas y carga los datos de ejemplo si la base esta vacia."""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) AS n FROM productos").fetchone()["n"] == 0:
            conn.executemany(
                "INSERT INTO proveedores (nombre, contacto) VALUES (?, ?)",
                PROVEEDORES_SEED,
            )
            proveedores = {
                r["nombre"]: r["id"] for r in conn.execute("SELECT id, nombre FROM proveedores")
            }
            for prefijo, nombre, cat, precio, stock, minimo, prov in PRODUCTOS_SEED:
                conn.execute(
                    """INSERT INTO productos
                       (codigo_barras, nombre, categoria, precio, stock_actual,
                        stock_minimo, proveedor_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (make_ean13(prefijo), nombre, cat, precio, stock, minimo,
                     proveedores[prov]),
                )
            # Movimientos historicos de ejemplo para el tablero de indicadores.
            arroz = conn.execute("SELECT id FROM productos WHERE nombre LIKE 'Arroz%'").fetchone()
            leche = conn.execute("SELECT id FROM productos WHERE nombre LIKE 'Leche%'").fetchone()
            cafe = conn.execute("SELECT id FROM productos WHERE nombre LIKE 'Café%'").fetchone()
            conn.execute(
                "INSERT INTO movimientos (producto_id, tipo, cantidad, motivo, fecha) "
                "VALUES (?, 'entrada', 40, 'Compra al mayorista', datetime('now', 'localtime', '-2 days'))",
                (arroz["id"],),
            )
            conn.execute(
                "INSERT INTO movimientos (producto_id, tipo, cantidad, motivo, fecha) "
                "VALUES (?, 'entrada', 48, 'Compra al mayorista', datetime('now', 'localtime', '-1 day'))",
                (leche["id"],),
            )
            conn.execute(
                "INSERT INTO movimientos (producto_id, tipo, cantidad, motivo, fecha) "
                "VALUES (?, 'salida', 20, 'Venta minorista', datetime('now', 'localtime', '-1 day'))",
                (cafe["id"],),
            )
            # Estado inicial de la lista de reposicion (cursograma CONTROL STOCK):
            # un pedido ya enviado al proveedor y dos faltantes anotados.
            def pid(nombre):
                return conn.execute(
                    "SELECT id FROM productos WHERE nombre LIKE ?", (f"{nombre}%",)
                ).fetchone()["id"]

            conn.execute(
                "INSERT INTO lista_reposicion (producto_id, cantidad_sugerida, estado) "
                "VALUES (?, 24, 'pedido')",
                (pid("Café"),),
            )
            conn.execute(
                "INSERT INTO lista_reposicion (producto_id, cantidad_sugerida, estado) "
                "VALUES (?, 20, 'anotado')",
                (pid("Harina"),),
            )
            conn.execute(
                "INSERT INTO lista_reposicion (producto_id, cantidad_sugerida, estado) "
                "VALUES (?, 24, 'anotado')",
                (pid("Detergente"),),
            )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Base inicializada en {DB_PATH}")
