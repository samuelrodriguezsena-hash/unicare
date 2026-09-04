# PostgreSQL local sin Docker (ni privilegios de administrador)

La vía normal de desarrollo es `docker compose up -d db`. Este documento cubre el caso en que
Docker no está disponible: los binarios oficiales de PostgreSQL se pueden ejecutar desde una
carpeta cualquiera, sin instalador y sin ser administrador.

Es un entorno **efímero de verificación**, no una instalación. No sustituye a `docker-compose`
y nada de esto se versiona.

## 1. Descargar y extraer

```bash
curl -sSL -o pg.zip https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip
```

El ZIP incluye pgAdmin y StackBuilder, que no hacen falta. Extraer sólo `bin`, `lib` y `share`
tarda un segundo, frente a varios minutos del ZIP completo:

```bash
python -c "import zipfile; z=zipfile.ZipFile('pg.zip'); z.extractall('pgx', members=[n for n in z.namelist() if n.startswith(('pgsql/bin/','pgsql/lib/','pgsql/share/'))])"
```

## 2. Inicializar y arrancar

Puerto no estándar para no chocar con nada, y `--auth=trust` porque sólo escucha en loopback:

```bash
pgx/pgsql/bin/initdb -D pgdata -U unicare --auth=trust --encoding=UTF8 --locale=C
```

```bash
pgx/pgsql/bin/pg_ctl -D pgdata -l pg.log -o "-p 55432 -c listen_addresses=127.0.0.1" -w start
```

```bash
pgx/pgsql/bin/createdb -h 127.0.0.1 -p 55432 -U unicare unicare
```

> `trust` sin contraseña es aceptable **sólo** aquí: escucha únicamente en `127.0.0.1` y no
> contiene datos reales. Nunca en un entorno compartido ni en producción.

## 3. Usarlo

```bash
export DATABASE_URL="postgres://unicare@127.0.0.1:55432/unicare"
```

```bash
python manage.py migrate
```

```bash
python -m pytest
```

Con la base accesible, `tests/test_schema_postgresql.py` deja de saltarse y verifica el esquema
físico contra el DER.

## 4. Parar y borrar

```bash
pgx/pgsql/bin/pg_ctl -D pgdata -m fast stop
```

Borrar `pgdata`, `pgx` y `pg.zip` elimina cualquier rastro: no se toca el registro de Windows,
ni servicios, ni `Archivos de programa`.

## Notas

- `psql` abre un pager que bloquea las sesiones no interactivas. Usar siempre `-P pager=off`.
- La salida de los binarios viene en español y en la codificación de la consola; para parsearla,
  conviene `-Atc` en lugar de la tabla formateada.
