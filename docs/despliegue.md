# Sacar la web del portátil

Cómo poner la web de Alberto en un servidor, detrás de Cloudflare, sin que parezca un proyecto a medias.
Lo que hay en el repo para esto: `Dockerfile`, `.dockerignore`, `docker-compose.yml` (referencia para
levantarlo todo en un ordenador con Docker) y `manage.py comprobar_despliegue`, que dice en llano qué falta.

## Por qué no Vercel
Vercel sirve funciones que arrancan y mueren con cada petición, sin disco y sin procesos que sigan vivos.
Esta web es lo contrario: un proceso que dura (DBOS y los hilos de repaso corren dentro del servidor), una
base de datos con fichero o servidor propio, PDF guardados en disco (`almacen/`) y un ERP que es otro
proceso aparte. El sitio natural es un contenedor: Railway, Fly.io o Render, con Postgres gestionado y un
disco persistente. Aquí va mascado para Railway; en Fly o Render son los mismos pasos con otros botones.

## Qué necesita para vivir fuera
- **Postgres**. La misma `DATABASE_URL` vale para la app y para DBOS: `config.py` la traduce al formato de
  Django (`base_de_datos_django`) y DBOS guarda su estado en la misma base, en su propio esquema `dbos`
  (`url_dbos`). No hay que crear nada a mano: `migrate` hace las tablas de la web al arrancar y DBOS las
  suyas la primera vez que se repasa un lote.
- **Un disco persistente** montado en `/datos`: ahí van los PDF que sube Alberto (`ALMACEN_DIR=/datos/almacen`,
  ya puesto en la imagen). Sin disco, cada despliegue se lleva las facturas subidas. `outputs/` es caché
  de trazas y se puede perder.
- **Variables** (las de `.env.example`, pero puestas en el panel del proveedor, nunca en un `.env` subido):
  - `DATABASE_URL`: `postgresql://usuario:clave@host:5432/base`.
  - `DJANGO_SECRET_KEY`: propia y larga (`python -c "import secrets; print(secrets.token_urlsafe(50))"`).
  - `DJANGO_ALLOWED_HOSTS`: el dominio, `facturas.tudominio.com`. `DJANGO_DEBUG` ya es `0` en la imagen.
  - `CSRF_TRUSTED_ORIGINS`: el mismo dominio con `https://` delante. Sin esto, los formularios se rechazan.
  - `HELMCODE_API_KEY` (y `HELMCODE_BASE_URL` si no es la de siempre): lee escaneos y evalúa notas.
  - `ASISTENTE_BASE_URL`, `ASISTENTE_API_KEY`, `ASISTENTE_MODELO`: el proveedor de «Preguntar»; sin ellas usa Helmcode.
  - `ERP_URL`, `ERP_USER`, `ERP_PASSWORD`: dónde está el ERP de Alberto (ver más abajo; `127.0.0.1` ya no vale).
  - `ALMACEN_DIR`: `/datos/almacen`, salvo que el disco se monte en otro sitio.
  - `HOY`: la fecha de referencia de «fecha no futura» (`2026-09-18`). Fija, los resultados no cambian con el calendario.
- **El ERP**. El bridge de 2009 solo escucha en `127.0.0.1` del ordenador donde arranca, así que el
  contenedor no lo ve. Para la demo, lo más simple: en el portátil que tenga La Caja,
  `python alberto_erp.py` y un túnel de Cloudflare hacia él (`cloudflared tunnel --url http://127.0.0.1:8009`
  da una URL `https://….trycloudflare.com`), y esa URL en `ERP_URL`. La web trabaja siempre con su copia
  del ERP (ADR-003): si el túnel se cae, decide con la última copia y «Conexión con el ERP» lo dice.

## Railway, paso a paso
1. Sube la rama a GitHub. En Railway: *New Project → Deploy from GitHub repo → upistas*. Detecta el
   `Dockerfile` y construye la imagen (unos minutos la primera vez).
2. En el mismo proyecto, *Create → Database → PostgreSQL*. En el servicio de la web, pestaña *Variables*,
   añade `DATABASE_URL` con el valor `${{Postgres.DATABASE_URL}}` (Railway lo rellena solo).
3. Servicio de la web → *Settings → Volumes → Add volume*, ruta de montaje `/datos`.
4. *Variables*: el resto de la lista de arriba. Lo que no cambie de `.env.example` no hace falta ponerlo.
5. *Settings → Networking*: puerto `8000`. *Custom domain* → `facturas.tudominio.com`; Railway te da el
   destino del CNAME para el paso de Cloudflare.
6. Redeploy. En los *Deploy logs* del arranque sale la lista de `comprobar_despliegue`: todo «Bien» y
   «Todo listo para desplegar.», o qué «Falta» y por qué. Arreglar y volver a desplegar hasta que esté limpio.
7. Cargar el maestro una vez: `railway ssh` (CLI de Railway, dentro del servicio de la web) y
   `python manage.py importar_maestro --excel …`, o subir los CSV desde «Importar datos» en la propia web.

En Fly.io: `fly launch` (lee el `Dockerfile`), `fly postgres create` + `fly postgres attach`,
`fly volumes create datos` y `[mounts] destination = "/datos"` en `fly.toml`, `fly secrets set` para las
variables. En Render: *Web Service* desde el repo con Docker, *PostgreSQL* gestionado y un *Disk* en `/datos`.

## Cloudflare delante
La web no tiene login a propósito (es de Alberto y de nadie más). Fuera del portátil, la puerta la pone
Cloudflare, no la web.

1. El dominio en Cloudflare (DNS gestionado por ellos). *DNS → Add record*: `CNAME facturas → <destino que
   dio Railway>`, con la nube naranja (*Proxied*) encendida. Así nadie ve la IP real ni salta el proxy.
2. *SSL/TLS → Overview*: modo **Full (strict)**. Railway sirve https con certificado válido; Cloudflare lo
   comprueba. Y en *Edge Certificates*, *Always Use HTTPS* encendido.
3. *Security → WAF*: el conjunto de reglas gestionadas gratuito, activado. Con eso van fuera los bots y los
   ataques de manual antes de llegar a la web.
4. **Cloudflare Access** (Zero Trust → *Access → Applications → Add an application → Self-hosted*), dominio
   `facturas.tudominio.com`. Una política *Allow* con la regla *Emails* y la lista de correos del equipo y
   de Alberto (o *Emails ending in* `@tudominio.com`). Método de entrada: *One-time PIN* (un código al
   correo, sin contraseña que recordar). Quien no esté en la lista no ve ni la portada.
5. Comprobar: abrir el dominio en una ventana privada → pide el correo → llega el PIN → entra la web.
   Subir un PDF y decidir uno de la cola, para ver que los formularios pasan (si un formulario da
   «CSRF verification failed», falta `CSRF_TRUSTED_ORIGINS` con `https://`).

## Publicar el portátil con un túnel de Cloudflare
Para una demo sin servidor: la web corre en el portátil y Cloudflare le da una dirección pública. Como
entraría cualquiera que la tenga, la web pide una clave (`WEB_CLAVE`) la primera vez y luego no la vuelve
a pedir en 16 horas.

1. Descargar `cloudflared` (https://github.com/cloudflare/cloudflared/releases; no hace falta cuenta).
2. Con la web arrancada (`uv run python manage.py runserver`), en otra terminal:
   `cloudflared tunnel --url http://127.0.0.1:8000`. Al momento imprime una dirección `https://….trycloudflare.com`.
3. En el `.env`:
   `DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,.trycloudflare.com`,
   `CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com` y
   `WEB_CLAVE=` con una clave que se pueda dictar por teléfono.
4. Reiniciar el servidor de la web para que lea el `.env`.
5. Abrir la dirección en una ventana privada: pide la clave, y con ella entra la web.

La dirección cambia cada vez que se arranca el túnel: hay que volver a pasarla. `ERP_URL` se queda como
está (`127.0.0.1:8009`), porque el ERP corre en el mismo portátil. `comprobar_despliegue` avisa si falta
`WEB_CLAVE`, pero no lo cuenta como fallo: con Cloudflare Access delante (arriba) la puerta ya la pone él.

## Lo que no se despliega
- **La Caja** (`../caja`, `data/`): datos del reto. La web los recibe por «Subir facturas», «Importar datos»
  e `importar_maestro`, no de la imagen.
- **`.env`**: las variables van en el panel del proveedor. `.dockerignore` lo deja fuera aunque alguien lo copie.
- **`outputs/`, `almacen/`, `*.sqlite`**: lo que genera el programa en el portátil. En el servidor nacen de nuevo.
- `tests/`, `docs/` y `.git`: no hacen falta para servir.

## Antes de la demo
- `comprobar_despliegue` en los logs del último arranque: todo «Bien», sin «Falta».
- El dominio abre por https con la nube naranja y pide el PIN a un correo que no esté en la lista.
- El maestro está cargado: «Proveedores» enseña los 11 de Alberto con sus pedidos.
- `ERP_URL` responde: «Conexión con el ERP» → «Sincronizar» trae asientos y no falla.
- Un repaso de prueba: subir dos PDF, ver la barra avanzar y la portada con las cifras.
- El disco `/datos` está montado: tras un redeploy, la factura subida sigue en su detalle.
- `HOY` puesta a la fecha del reto, la misma que en los portátiles, para que los resultados cuadren con
  `outputs/outcomes.jsonl` de la entrega.
- Las claves (`HELMCODE_API_KEY`, `ASISTENTE_API_KEY`) tienen saldo: probar «Preguntar» y una factura escaneada.
