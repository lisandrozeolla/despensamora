# Sistema de Control de Stock — Despensa Mora

Sistema web local para el control de stock de un almacén, con soporte de
lector de codigos de barras USB (funciona como teclado).

## Requisitos

- Python 3.10 o superior
- `pip install -r requirements.txt` (Flask y python-barcode)

## Ejecutar

```
python app.py
```

Abrir <http://127.0.0.1:5000> en el navegador.

La base SQLite (`stock.db`) se crea sola con datos de ejemplo. Para
reiniciarla de cero: borrá `stock.db` y volvé a ejecutar `python db.py`.

## Lector de codigos de barras

Conectá el lector USB: enfocá la barra superior ("Escaneá el código de
barras…") y escaneá. El lector escribe el codigo y envia Enter
automaticamente. Sin lector, se puede escribir el codigo a mano.

## Pantallas

| Pantalla | Funcion |
|---|---|
| Tablero | Valor del stock, faltantes, bajo minimo, ultimos movimientos |
| Venta | Escaneo, carrito, validacion de stock y registro de salidas |
| Ingresos | Recepcion de pedidos (ingreso o reclamo) e ingreso directo |
| Reposición | Lista de reposicion: anotados → pedido → recibido/reclamo |
| Productos | Alta, baja y edicion del maestro (codigo de barras, precio, stock) |
| Proveedores | Alta y baja de proveedores |
| Etiquetas | Generacion e impresion de etiquetas EAN-13 |
