#falta pdoer ver ventas pasadas

"""Sistema de Control de Stock - Despensa Mora.

Flask sirve las vistas (HTML) y una API JSON que implementa el flujo
del cursograma "CONTROL STOCK":
  venta con validacion de stock -> alta automatica en lista de reposicion
  -> pedido al proveedor -> recepcion (ingreso o reclamo).
"""
import io
from datetime import datetime

import barcode
from barcode.writer import SVGWriter
from flask import Flask, Response, jsonify, render_template, request

import db

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _error(mensaje: str, codigo: int = 400):
    return jsonify(error=mensaje), codigo


def _producto(conn, producto_id: int):
    return conn.execute(
        "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
        "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
        "WHERE p.id = ?",
        (producto_id,),
    ).fetchone()


def _buscar_por_codigo(conn, codigo: str):
    """Busca un producto escaneando: primero por codigo exacto, luego por id."""
    fila = conn.execute(
        "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
        "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
        "WHERE p.codigo_barras = ?",
        (codigo,),
    ).fetchone()
    if fila is None and codigo.isdigit():
        fila = _producto(conn, int(codigo))
    return fila


def _asegurar_reposicion(conn, producto_id: int, motivo: str = "Stock minimo"):
    """Anota el producto en la lista de reposicion si no tiene un caso abierto.

    Corresponde al paso 'Anotar para lista de Reposicion' del cursograma.
    """
    abierto = conn.execute(
        "SELECT id FROM lista_reposicion "
        "WHERE producto_id = ? AND estado IN ('anotado', 'pedido')",
        (producto_id,),
    ).fetchone()
    if abierto:
        return False
    prod = conn.execute(
        "SELECT stock_actual, stock_minimo FROM productos WHERE id = ?",
        (producto_id,),
    ).fetchone()
    sugerida = max(prod["stock_minimo"] * 2, 10)
    conn.execute(
        "INSERT INTO lista_reposicion (producto_id, cantidad_sugerida) VALUES (?, ?)",
        (producto_id, sugerida),
    )
    app.logger.info("Reposicion automatica (%s): producto %s", motivo, producto_id)
    return True


def _registrar_movimiento(conn, producto_id: int, tipo: str, cantidad: int, motivo: str):
    conn.execute(
        "INSERT INTO movimientos (producto_id, tipo, cantidad, motivo) VALUES (?, ?, ?, ?)",
        (producto_id, tipo, cantidad, motivo),
    )


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------

@app.route("/")
def vista_dashboard():
    return render_template("dashboard.html", activo="dashboard")


@app.route("/venta")
def vista_venta():
    return render_template("venta.html", activo="venta")


@app.route("/ingreso")
def vista_ingreso():
    return render_template("ingreso.html", activo="ingreso")


@app.route("/productos")
def vista_productos():
    return render_template("productos.html", activo="productos")


@app.route("/proveedores")
def vista_proveedores():
    return render_template("proveedores.html", activo="proveedores")


@app.route("/reposicion")
def vista_reposicion():
    return render_template("reposicion.html", activo="reposicion")


@app.route("/etiquetas")
def vista_etiquetas():
    return render_template("etiquetas.html", activo="etiquetas")


# Diagrama de contexto: "Solicitud de reposicion" -> Dueño.
# Vista imprimible de los productos anotados y pedidos al proveedor.
@app.route("/imprimir/reposicion")
def vista_imprimir_reposicion():
    proveedor_id = request.args.get("proveedor_id", type=int)
    conn = db.get_conn()
    try:
        sql = (
            "SELECT r.*, p.nombre, p.codigo_barras, p.stock_actual, p.stock_minimo, "
            "       COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
            "FROM lista_reposicion r "
            "JOIN productos p ON p.id = r.producto_id "
            "LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
            "WHERE r.estado IN ('anotado', 'pedido')"
        )
        params = []
        if proveedor_id:
            sql += " AND p.proveedor_id = ?"
            params.append(proveedor_id)
        sql += " ORDER BY pr.nombre, p.nombre"
        items = conn.execute(sql, params).fetchall()
        if proveedor_id:
            fila = conn.execute(
                "SELECT nombre FROM proveedores WHERE id = ?", (proveedor_id,)
            ).fetchone()
            proveedor = fila["nombre"] if fila else "Todos los proveedores"
        else:
            proveedor = "Todos los proveedores"
        return render_template(
            "imprimir_reposicion.html",
            items=[dict(i) for i in items],
            proveedor=proveedor,
            fecha=datetime.now().strftime("%d/%m/%Y %H:%M"),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: productos
# ---------------------------------------------------------------------------

@app.route("/api/productos", methods=["GET"])
def api_productos():
    q = (request.args.get("q") or "").strip()
    conn = db.get_conn()
    try:
        if q:
            filas = conn.execute(
                "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
                "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
                "WHERE p.nombre LIKE ? OR p.codigo_barras LIKE ? OR p.categoria LIKE ? "
                "ORDER BY p.nombre",
                (f"%{q}%", f"%{q}%", f"%{q}%"),
            ).fetchall()
        else:
            filas = conn.execute(
                "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
                "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
                "ORDER BY p.nombre"
            ).fetchall()
        return jsonify([dict(f) for f in filas])
    finally:
        conn.close()


@app.route("/api/productos/buscar", methods=["GET"])
def api_producto_buscar():
    codigo = (request.args.get("codigo") or "").strip()
    if not codigo:
        return _error("Falta el codigo")
    conn = db.get_conn()
    try:
        fila = _buscar_por_codigo(conn, codigo)
        if fila is None:
            return _error("Producto no encontrado", 404)
        return jsonify(dict(fila))
    finally:
        conn.close()


@app.route("/api/productos", methods=["POST"])
def api_producto_alta():
    data = request.get_json(silent=True) or {}
    codigo = str(data.get("codigo_barras", "")).strip()
    nombre = str(data.get("nombre", "")).strip()
    if not codigo or not nombre:
        return _error("El codigo de barras y el nombre son obligatorios")
    try:
        precio = float(data.get("precio", 0) or 0)
        stock = int(data.get("stock_actual", 0) or 0)
        minimo = int(data.get("stock_minimo", 0) or 0)
    except (TypeError, ValueError):
        return _error("Precio, stock y minimo deben ser numericos")
    if precio < 0 or stock < 0 or minimo < 0:
        return _error("Los valores no pueden ser negativos")
    conn = db.get_conn()
    try:
        existe = conn.execute(
            "SELECT id FROM productos WHERE codigo_barras = ?", (codigo,)
        ).fetchone()
        if existe:
            return _error(f"Ya existe un producto con el codigo {codigo}", 409)
        cur = conn.execute(
            """INSERT INTO productos
               (codigo_barras, nombre, categoria, precio, stock_actual,
                stock_minimo, proveedor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (codigo, nombre, str(data.get("categoria", "")).strip(), precio,
             stock, minimo, data.get("proveedor_id") or None),
        )
        conn.commit()
        return jsonify(dict(_producto(conn, cur.lastrowid))), 201
    finally:
        conn.close()


@app.route("/api/productos/<int:producto_id>", methods=["PUT"])
def api_producto_editar(producto_id: int):
    data = request.get_json(silent=True) or {}
    conn = db.get_conn()
    try:
        actual = _producto(conn, producto_id)
        if actual is None:
            return _error("Producto no encontrado", 404)
        nombre = str(data.get("nombre", actual["nombre"])).strip()
        codigo = str(data.get("codigo_barras", actual["codigo_barras"])).strip()
        if not nombre or not codigo:
            return _error("El codigo y el nombre no pueden quedar vacios")
        duplicado = conn.execute(
            "SELECT id FROM productos WHERE codigo_barras = ? AND id != ?",
            (codigo, producto_id),
        ).fetchone()
        if duplicado:
            return _error(f"Otro producto ya usa el codigo {codigo}", 409)
        try:
            precio = float(data.get("precio", actual["precio"]))
            stock = int(data.get("stock_actual", actual["stock_actual"]))
            minimo = int(data.get("stock_minimo", actual["stock_minimo"]))
        except (TypeError, ValueError):
            return _error("Precio, stock y minimo deben ser numericos")
        conn.execute(
            """UPDATE productos
               SET codigo_barras = ?, nombre = ?, categoria = ?, precio = ?,
                   stock_actual = ?, stock_minimo = ?, proveedor_id = ?
               WHERE id = ?""",
            (codigo, nombre, str(data.get("categoria", actual["categoria"])).strip(),
             precio, stock, minimo,
             data.get("proveedor_id") or actual["proveedor_id"], producto_id),
        )
        # Si la edicion deja el stock en el minimo, entra en la lista de reposicion.
        if stock <= minimo:
            _asegurar_reposicion(conn, producto_id, "Edicion de producto")
        conn.commit()
        return jsonify(dict(_producto(conn, producto_id)))
    finally:
        conn.close()


@app.route("/api/productos/<int:producto_id>", methods=["DELETE"])
def api_producto_baja(producto_id: int):
    conn = db.get_conn()
    try:
        actual = _producto(conn, producto_id)
        if actual is None:
            return _error("Producto no encontrado", 404)
        conn.execute("DELETE FROM lista_reposicion WHERE producto_id = ?", (producto_id,))
        conn.execute("DELETE FROM movimientos WHERE producto_id = ?", (producto_id,))
        conn.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: proveedores
# ---------------------------------------------------------------------------

@app.route("/api/proveedores", methods=["GET"])
def api_proveedores():
    conn = db.get_conn()
    try:
        filas = conn.execute(
            """SELECT pr.*, COUNT(p.id) AS productos
               FROM proveedores pr LEFT JOIN productos p ON p.proveedor_id = pr.id
               GROUP BY pr.id ORDER BY pr.nombre"""
        ).fetchall()
        return jsonify([dict(f) for f in filas])
    finally:
        conn.close()


@app.route("/api/proveedores", methods=["POST"])
def api_proveedor_alta():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return _error("El nombre del proveedor es obligatorio")
    conn = db.get_conn()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO proveedores (nombre, contacto) VALUES (?, ?)",
                (nombre, str(data.get("contacto", "")).strip()),
            )
        except Exception:
            return _error(f"Ya existe el proveedor {nombre}", 409)
        conn.commit()
        return jsonify(dict(conn.execute(
            "SELECT * FROM proveedores WHERE id = ?", (cur.lastrowid,)
        ).fetchone())), 201
    finally:
        conn.close()


@app.route("/api/proveedores/<int:proveedor_id>", methods=["DELETE"])
def api_proveedor_baja(proveedor_id: int):
    conn = db.get_conn()
    try:
        en_uso = conn.execute(
            "SELECT COUNT(*) AS n FROM productos WHERE proveedor_id = ?",
            (proveedor_id,),
        ).fetchone()["n"]
        if en_uso:
            return _error(
                f"No se puede eliminar: tiene {en_uso} producto(s) asociados", 409
            )
        conn.execute("DELETE FROM proveedores WHERE id = ?", (proveedor_id,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: venta (salida de stock) - cursograma "Hay stock? -> Registrar salida"
# ---------------------------------------------------------------------------

@app.route("/api/venta", methods=["POST"])
def api_venta():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return _error("La venta no tiene productos")
    conn = db.get_conn()
    try:
        # Primero valida TODO el carrito: si algo no alcanza, no se registra nada.
        carrito = []
        for item in items:
            producto = _producto(conn, int(item.get("producto_id", 0)))
            if producto is None:
                return _error("Producto inexistente en la venta", 404)
            try:
                cantidad = int(item.get("cantidad", 0))
            except (TypeError, ValueError):
                return _error("Cantidad invalida")
            if cantidad <= 0:
                return _error(f"Cantidad invalida para {producto['nombre']}")
            if producto["stock_actual"] < cantidad:
                return _error(
                    f"Stock insuficiente de {producto['nombre']} "
                    f"(disponible: {producto['stock_actual']})",
                    409,
                )
            carrito.append((producto, cantidad))

        # Todo OK: descuenta stock y registra las salidas.
        for producto, cantidad in carrito:
            conn.execute(
                "UPDATE productos SET stock_actual = stock_actual - ? WHERE id = ?",
                (cantidad, producto["id"]),
            )
            _registrar_movimiento(conn, producto["id"], "salida", cantidad, "Venta minorista")
            stock_restante = producto["stock_actual"] - cantidad
            # "¿Quedan pocas unidades? -> Anotar para lista de Reposicion"
            if stock_restante <= producto["stock_minimo"]:
                _asegurar_reposicion(conn, producto["id"], "Venta")
        conn.commit()
        total = sum(p["precio"] * c for p, c in carrito)
        return jsonify(
            ok=True,
            total=total,
            items=[
                {"nombre": p["nombre"], "cantidad": c, "precio": p["precio"]}
                for p, c in carrito
            ],
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: ingreso de mercadería (entrada de stock)
# ---------------------------------------------------------------------------

@app.route("/api/ingreso", methods=["POST"])
def api_ingreso():
    """Ingreso directo: compra mayorista/minorista cargada escaneando."""
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return _error("El ingreso no tiene productos")
    conn = db.get_conn()
    try:
        cargados = []
        for item in items:
            producto = _producto(conn, int(item.get("producto_id", 0)))
            if producto is None:
                return _error("Producto inexistente en el ingreso", 404)
            try:
                cantidad = int(item.get("cantidad", 1))
            except (TypeError, ValueError):
                return _error("Cantidad invalida")
            if cantidad <= 0:
                return _error(f"Cantidad invalida para {producto['nombre']}")
            conn.execute(
                "UPDATE productos SET stock_actual = stock_actual + ? WHERE id = ?",
                (cantidad, producto["id"]),
            )
            _registrar_movimiento(conn, producto["id"], "entrada", cantidad,
                                  "Ingreso de mercadería")
            cargados.append({"nombre": producto["nombre"], "cantidad": cantidad})
        conn.commit()
        return jsonify(ok=True, items=cargados)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: lista de reposicion (faltantes -> pedido -> recepcion/reclamo)
# ---------------------------------------------------------------------------

@app.route("/api/reposicion", methods=["GET"])
def api_reposicion_lista():
    estado = (request.args.get("estado") or "").strip()
    conn = db.get_conn()
    try:
        sql = (
            "SELECT r.*, p.nombre, p.codigo_barras, p.stock_actual, p.stock_minimo, "
            "       COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
            "FROM lista_reposicion r "
            "JOIN productos p ON p.id = r.producto_id "
            "LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
        )
        params = ()
        if estado:
            sql += " WHERE r.estado = ?"
            params = (estado,)
        sql += " ORDER BY CASE r.estado WHEN 'pedido' THEN 0 WHEN 'anotado' THEN 1 "
        sql += "ELSE 2 END, r.fecha DESC"
        filas = conn.execute(sql, params).fetchall()
        return jsonify([dict(f) for f in filas])
    finally:
        conn.close()


@app.route("/api/reposicion", methods=["POST"])
def api_reposicion_anotar():
    """Paso 'Anotar producto en lista de Reposicion' del cursograma."""
    data = request.get_json(silent=True) or {}
    conn = db.get_conn()
    try:
        producto = None
        if data.get("producto_id"):
            producto = _producto(conn, int(data["producto_id"]))
        elif data.get("codigo"):
            producto = _buscar_por_codigo(conn, str(data["codigo"]).strip())
        if producto is None:
            return _error("Producto no encontrado", 404)
        if _asegurar_reposicion(conn, producto["id"], "Manual"):
            conn.commit()
            return jsonify(ok=True, mensaje=f"{producto['nombre']} anotado en la lista de reposicion")
        return jsonify(ok=True, mensaje=f"{producto['nombre']} ya estaba en la lista")
    finally:
        conn.close()


@app.route("/api/reposicion/anotar-minimos", methods=["POST"])
def api_reposicion_anotar_minimos():
    """Anota de una vez todos los productos que llegaron al stock minimo."""
    conn = db.get_conn()
    try:
        filas = conn.execute(
            "SELECT id FROM productos WHERE stock_actual <= stock_minimo"
        ).fetchall()
        nuevos = sum(1 for f in filas if _asegurar_reposicion(conn, f["id"], "Minimos"))
        conn.commit()
        return jsonify(ok=True, anotados=nuevos, revisados=len(filas))
    finally:
        conn.close()


@app.route("/api/reposicion/generar-pedido", methods=["POST"])
def api_reposicion_generar_pedido():
    """Paso 'Pedido al Proveedor': pasa los casos anotados a estado 'pedido'."""
    data = request.get_json(silent=True) or {}
    proveedor_id = data.get("proveedor_id")
    conn = db.get_conn()
    try:
        sql = (
            "UPDATE lista_reposicion SET estado = 'pedido' "
            "WHERE estado = 'anotado' AND producto_id IN "
            "  (SELECT id FROM productos WHERE (? IS NULL OR proveedor_id = ?))"
        )
        cur = conn.execute(sql, (proveedor_id, proveedor_id))
        conn.commit()
        if cur.rowcount == 0:
            return _error("No hay productos anotados para pedir", 409)
        return jsonify(ok=True, pedidos=cur.rowcount)
    finally:
        conn.close()


@app.route("/api/reposicion/<int:item_id>/recepcion", methods=["POST"])
def api_reposicion_recepcion(item_id: int):
    """Recepcion del pedido: '¿Llego todo en buen estado?'.

    reclamo=False -> carga el ingreso en el sistema (suma stock);
                     acepta casos anotados, pedidos o en reclamo.
    reclamo=True  -> marca el reclamo al proveedor (no suma stock).
    """
    data = request.get_json(silent=True) or {}
    reclamo = bool(data.get("reclamo"))
    conn = db.get_conn()
    try:
        item = conn.execute(
            "SELECT r.*, p.nombre, p.stock_actual "
            "FROM lista_reposicion r JOIN productos p ON p.id = r.producto_id "
            "WHERE r.id = ?",
            (item_id,),
        ).fetchone()
        if item is None:
            return _error("Item de reposicion no encontrado", 404)
        estados = ("anotado", "pedido") if reclamo else ("anotado", "pedido", "reclamo")
        if item["estado"] not in estados:
            return _error(f"El caso de {item['nombre']} ya fue cerrado", 409)
        if reclamo:
            conn.execute(
                "UPDATE lista_reposicion SET estado = 'reclamo' WHERE id = ?",
                (item_id,),
            )
            conn.commit()
            return jsonify(
                ok=True,
                mensaje=f"Reclamo registrado al proveedor por {item['nombre']}",
            )
        try:
            cantidad = int(data.get("cantidad", item["cantidad_sugerida"]))
        except (TypeError, ValueError):
            return _error("Cantidad invalida")
        if cantidad <= 0:
            return _error("La cantidad recibida debe ser mayor a cero")
        conn.execute(
            "UPDATE productos SET stock_actual = stock_actual + ? WHERE id = ?",
            (cantidad, item["producto_id"]),
        )
        _registrar_movimiento(conn, item["producto_id"], "entrada", cantidad,
                              "Recepción de pedido")
        conn.execute(
            "UPDATE lista_reposicion SET estado = 'recibido' WHERE id = ?",
            (item_id,),
        )
        conn.commit()
        return jsonify(ok=True, mensaje=f"Ingreso cargado: {item['nombre']} (+{cantidad})")
    finally:
        conn.close()


# Cursograma: el reclamo se reintenta y vuelve al paso "Pedido al Proveedor".
@app.route("/api/reposicion/<int:item_id>/volver-pedido", methods=["POST"])
def api_reposicion_volver_pedido(item_id: int):
    """Pasa un caso en 'reclamo' de vuelta al estado 'pedido'."""
    conn = db.get_conn()
    try:
        item = conn.execute(
            "SELECT estado FROM lista_reposicion WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            return _error("Item de reposicion no encontrado", 404)
        if item["estado"] != "reclamo":
            return _error("Solo los casos en reclamo vuelven a pedido", 409)
        conn.execute(
            "UPDATE lista_reposicion SET estado = 'pedido' WHERE id = ?", (item_id,)
        )
        conn.commit()
        return jsonify(ok=True, mensaje="Caso devuelto al estado pedido")
    finally:
        conn.close()


# Limpieza de la lista: quita el caso sin tocar stock ni movimientos.
@app.route("/api/reposicion/<int:item_id>", methods=["DELETE"])
def api_reposicion_quitar(item_id: int):
    """Elimina un caso de la lista de reposicion (limpieza)."""
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM lista_reposicion WHERE id = ?", (item_id,)
        )
        conn.commit()
        if cur.rowcount == 0:
            return _error("Item de reposicion no encontrado", 404)
        return jsonify(ok=True, mensaje="Caso eliminado de la lista")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: alertas, tablero y movimientos
# ---------------------------------------------------------------------------

@app.route("/api/alertas", methods=["GET"])
def api_alertas():
    conn = db.get_conn()
    try:
        faltantes = conn.execute(
            "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
            "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
            "WHERE p.stock_actual = 0 ORDER BY p.nombre"
        ).fetchall()
        bajos = conn.execute(
            "SELECT p.*, COALESCE(pr.nombre, 'Sin proveedor') AS proveedor "
            "FROM productos p LEFT JOIN proveedores pr ON pr.id = p.proveedor_id "
            "WHERE p.stock_actual > 0 AND p.stock_actual <= p.stock_minimo "
            "ORDER BY p.nombre"
        ).fetchall()
        reclamos = conn.execute(
            "SELECT COUNT(*) AS n FROM lista_reposicion WHERE estado = 'reclamo'"
        ).fetchone()["n"]
        return jsonify(
            faltantes=[dict(f) for f in faltantes],
            bajo_minimo=[dict(b) for b in bajos],
            reclamos=reclamos,
            total=len(faltantes) + len(bajos) + reclamos,
        )
    finally:
        conn.close()


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    conn = db.get_conn()
    try:
        totales = conn.execute(
            """SELECT COUNT(*) AS productos,
                      COALESCE(SUM(stock_actual), 0) AS unidades,
                      COALESCE(SUM(stock_actual * precio), 0) AS valor
               FROM productos"""
        ).fetchone()
        alertas = conn.execute(
            """SELECT
                 SUM(CASE WHEN stock_actual = 0 THEN 1 ELSE 0 END) AS faltantes,
                 SUM(CASE WHEN stock_actual > 0 AND stock_actual <= stock_minimo
                          THEN 1 ELSE 0 END) AS bajos
               FROM productos"""
        ).fetchone()
        pendientes = conn.execute(
            "SELECT COUNT(*) AS n FROM lista_reposicion WHERE estado IN ('anotado', 'pedido')"
        ).fetchone()["n"]
        ventas_hoy = conn.execute(
            """SELECT COALESCE(SUM(cantidad), 0) AS n FROM movimientos
               WHERE tipo = 'salida' AND date(fecha) = date('now', 'localtime')"""
        ).fetchone()["n"]
        entradas_hoy = conn.execute(
            """SELECT COALESCE(SUM(cantidad), 0) AS n FROM movimientos
               WHERE tipo = 'entrada' AND date(fecha) = date('now', 'localtime')"""
        ).fetchone()["n"]
        movimientos = conn.execute(
            """SELECT m.*, p.nombre AS producto, p.codigo_barras
               FROM movimientos m JOIN productos p ON p.id = m.producto_id
               ORDER BY m.id DESC LIMIT 15"""
        ).fetchall()
        return jsonify(
            productos=totales["productos"],
            unidades=totales["unidades"],
            valor=round(totales["valor"], 2),
            faltantes=alertas["faltantes"] or 0,
            bajos=alertas["bajos"] or 0,
            pendientes=pendientes,
            ventas_hoy=ventas_hoy,
            entradas_hoy=entradas_hoy,
            movimientos=[dict(m) for m in movimientos],
        )
    finally:
        conn.close()


@app.route("/api/movimientos", methods=["GET"])
def api_movimientos():
    conn = db.get_conn()
    try:
        filas = conn.execute(
            """SELECT m.*, p.nombre AS producto, p.codigo_barras
               FROM movimientos m JOIN productos p ON p.id = m.producto_id
               ORDER BY m.id DESC LIMIT ?""",
            (int(request.args.get("limit", 50)),),
        ).fetchall()
        return jsonify([dict(f) for f in filas])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: etiqueta con codigo de barras (EAN-13 / CODE128 en SVG)
# ---------------------------------------------------------------------------

def _generar_svg(codigo: str) -> bytes:
    """Genera la etiqueta SVG. Usa EAN-13 y si el codigo no es valido, CODE128."""
    opciones = {
        "module_width": 0.4,
        "module_height": 14.0,
        "font_size": 11,
        "quiet_zone": 5,
        "text_distance": 5,
    }
    for nombre in ("ean13", "code128"):
        try:
            objeto = barcode.get(nombre, codigo, writer=SVGWriter())
            buffer = io.BytesIO()
            objeto.write(buffer, options=opciones)
            return buffer.getvalue()
        except Exception:  # el codigo no es valido para este formato
            continue
    raise ValueError("No se pudo generar el codigo de barras")


@app.route("/api/etiqueta/<int:producto_id>", methods=["GET"])
def api_etiqueta(producto_id: int):
    conn = db.get_conn()
    try:
        producto = _producto(conn, producto_id)
        if producto is None:
            return _error("Producto no encontrado", 404)
        svg = _generar_svg(producto["codigo_barras"])
        return Response(svg, mimetype="image/svg+xml")
    finally:
        conn.close()


if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
