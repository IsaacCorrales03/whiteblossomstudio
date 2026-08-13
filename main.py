from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import os
import re
import uuid
import calendar
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-en-produccion"

BASE_DIR = os.path.dirname(__file__)
USERS_FILE = os.path.join(BASE_DIR, "users.json")
TASKS_FILE = os.path.join(BASE_DIR, "data", "tasks.json")
PERSONAL_FILE = os.path.join(BASE_DIR, "data", "personal.json")
CHAT_FILE = os.path.join(BASE_DIR, "data", "chat.json")
CHAT_SEEN_FILE = os.path.join(BASE_DIR, "data", "chat_seen.json")
MEETINGS_FILE = os.path.join(BASE_DIR, "data", "meetings.json")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------- Helpers de almacenamiento ----------
def cargar_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cargar_usuarios():
    return cargar_json(USERS_FILE, [])


def guardar_usuarios(usuarios):
    guardar_json(USERS_FILE, usuarios)


def obtener_usuario(nombre):
    for u in cargar_usuarios():
        if u["nombre"].lower() == nombre.lower():
            return u
    return None


def requiere_login():
    return "nombre" not in session


def es_administrador():
    return session.get("rol") in ("Administrador", "Administradora")


def archivo_permitido(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ---------- Autenticación ----------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")

        usuario_encontrado = None
        for u in cargar_usuarios():
            if u["nombre"].lower() == nombre.lower() and u["password"] == password:
                usuario_encontrado = u
                break

        if usuario_encontrado:
            session["nombre"] = usuario_encontrado["nombre"]
            session["rol"] = usuario_encontrado["rol"]
            session["puesto"] = usuario_encontrado.get("puesto", "")
            return redirect(url_for("menu"))
        else:
            flash("Nombre o contraseña incorrectos")
            return redirect(url_for("index"))

    return render_template("index.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


def contexto_usuario():
    """Datos comunes que casi todas las plantillas necesitan."""
    usuario = obtener_usuario(session["nombre"])
    return {
        "nombre": session["nombre"],
        "rol": session["rol"],
        "puesto": session.get("puesto", ""),
        "foto": usuario.get("foto") if usuario else None,
    }


# ---------- Tablero (menú principal) ----------
@app.route("/menu")
def menu():
    if requiere_login():
        return redirect(url_for("index"))

    tareas_todas = cargar_json(TASKS_FILE, [])
    es_admin = session["rol"] in ("Administrador", "Administradora")

    if es_admin:
        tareas = tareas_todas
    else:
        tareas = [t for t in tareas_todas if t["asignado_a"] == session["nombre"]]

    activos = len(tareas)
    completados = len([t for t in tareas if t["estado"] == "completado"])
    pendientes = len([t for t in tareas if t["estado"] == "pendiente"])
    atrasados = len([t for t in tareas if t["estado"] == "atrasado"])

    reuniones_prox = reuniones_de_usuario(session["nombre"], es_admin)[:4]

    return render_template(
        "menu.html",
        **contexto_usuario(),
        activos=activos,
        completados=completados,
        pendientes=pendientes,
        atrasados=atrasados,
        tareas=tareas[:5],
        reuniones_prox=reuniones_prox,
    )


# ---------- Objetivos de la semana ----------
@app.route("/objetivos-semana", methods=["GET", "POST"])
def objetivos_semana():
    if requiere_login():
        return redirect(url_for("index"))

    tareas = cargar_json(TASKS_FILE, [])

    if request.method == "POST":
        if session["rol"] not in ("Administrador", "Administradora"):
            flash("No tienes permiso para asignar objetivos")
            return redirect(url_for("objetivos_semana"))

        nuevo_id = (max([t["id"] for t in tareas]) + 1) if tareas else 1
        tareas.append({
            "id": nuevo_id,
            "titulo": request.form.get("titulo", "").strip(),
            "descripcion": request.form.get("descripcion", "").strip(),
            "asignado_a": request.form.get("asignado_a", "").strip(),
            "vence": request.form.get("vence", ""),
            "estado": "pendiente",
        })
        guardar_json(TASKS_FILE, tareas)
        flash("Objetivo asignado")
        return redirect(url_for("objetivos_semana"))

    usuarios = cargar_usuarios()
    es_admin = session["rol"] in ("Administrador", "Administradora")

    if es_admin:
        tareas_visibles = tareas
    else:
        tareas_visibles = [t for t in tareas if t["asignado_a"] == session["nombre"]]

    return render_template(
        "objetivos_semana.html",
        **contexto_usuario(),
        tareas=tareas_visibles,
        usuarios=usuarios,
    )


@app.route("/objetivos-semana/<int:tarea_id>/estado", methods=["POST"])
def cambiar_estado_tarea(tarea_id):
    if requiere_login():
        return redirect(url_for("index"))

    tareas = cargar_json(TASKS_FILE, [])
    es_admin = session["rol"] in ("Administrador", "Administradora")

    tarea = next((t for t in tareas if t["id"] == tarea_id), None)
    if tarea is None:
        return redirect(url_for("objetivos_semana"))

    if not es_admin and tarea["asignado_a"] != session["nombre"]:
        flash("No tienes permiso para modificar ese objetivo")
        return redirect(url_for("objetivos_semana"))

    nuevo_estado = request.form.get("estado")
    tarea["estado"] = nuevo_estado
    guardar_json(TASKS_FILE, tareas)
    return redirect(url_for("objetivos_semana"))


# ---------- Objetivos personales ----------
@app.route("/objetivos-personales", methods=["GET", "POST"])
def objetivos_personales():
    if requiere_login():
        return redirect(url_for("index"))

    personal = cargar_json(PERSONAL_FILE, {})
    lista = personal.get(session["nombre"], [])

    if request.method == "POST":
        texto = request.form.get("texto", "").strip()
        if texto:
            nuevo_id = (max([i["id"] for i in lista]) + 1) if lista else 1
            lista.append({"id": nuevo_id, "texto": texto, "hecho": False})
            personal[session["nombre"]] = lista
            guardar_json(PERSONAL_FILE, personal)
        return redirect(url_for("objetivos_personales"))

    return render_template(
        "objetivos_personales.html",
        **contexto_usuario(),
        items=lista,
    )


@app.route("/objetivos-personales/<int:item_id>/toggle", methods=["POST"])
def toggle_objetivo_personal(item_id):
    if requiere_login():
        return redirect(url_for("index"))

    personal = cargar_json(PERSONAL_FILE, {})
    lista = personal.get(session["nombre"], [])
    for i in lista:
        if i["id"] == item_id:
            i["hecho"] = not i["hecho"]
            break
    personal[session["nombre"]] = lista
    guardar_json(PERSONAL_FILE, personal)
    return redirect(url_for("objetivos_personales"))


@app.route("/objetivos-personales/<int:item_id>/eliminar", methods=["POST"])
def eliminar_objetivo_personal(item_id):
    if requiere_login():
        return redirect(url_for("index"))

    personal = cargar_json(PERSONAL_FILE, {})
    lista = personal.get(session["nombre"], [])
    lista = [i for i in lista if i["id"] != item_id]
    personal[session["nombre"]] = lista
    guardar_json(PERSONAL_FILE, personal)
    return redirect(url_for("objetivos_personales"))


# ---------- Chat de equipo ----------
@app.route("/chat")
def chat():
    if requiere_login():
        return redirect(url_for("index"))

    mensajes = cargar_json(CHAT_FILE, [])

    # Al abrir el chat, se marca todo como leído
    vistos = cargar_json(CHAT_SEEN_FILE, {})
    if mensajes:
        vistos[session["nombre"]] = mensajes[-1]["id"]
        guardar_json(CHAT_SEEN_FILE, vistos)

    usuarios = [u["nombre"] for u in cargar_usuarios()]

    return render_template(
        "chat.html",
        **contexto_usuario(),
        mensajes=mensajes,
        usuarios=usuarios,
    )


@app.route("/chat/enviar", methods=["POST"])
def chat_enviar():
    if requiere_login():
        return jsonify({"error": "no autenticado"}), 401

    texto = request.form.get("texto", "").strip()
    if not texto:
        return jsonify({"error": "mensaje vacío"}), 400

    mensajes = cargar_json(CHAT_FILE, [])
    nuevo_id = (mensajes[-1]["id"] + 1) if mensajes else 1
    usuario = obtener_usuario(session["nombre"])

    # Detectar menciones @Nombre contra la lista real de usuarios
    nombres_validos = [u["nombre"] for u in cargar_usuarios()]
    menciones = []
    for n in nombres_validos:
        if re.search(r"(?<![\w])@" + re.escape(n) + r"(?![\w])", texto, re.IGNORECASE):
            menciones.append(n)

    mensaje = {
        "id": nuevo_id,
        "autor": session["nombre"],
        "foto": usuario.get("foto") if usuario else None,
        "texto": texto[:2000],
        "hora": datetime.now().strftime("%H:%M"),
        "menciones": menciones,
    }
    mensajes.append(mensaje)

    # Se conserva solo el historial reciente para que el archivo no crezca sin límite
    mensajes = mensajes[-500:]
    guardar_json(CHAT_FILE, mensajes)

    # Quien envía también queda al día
    vistos = cargar_json(CHAT_SEEN_FILE, {})
    vistos[session["nombre"]] = nuevo_id
    guardar_json(CHAT_SEEN_FILE, vistos)

    return jsonify(mensaje)


@app.route("/chat/mensajes")
def chat_mensajes():
    """Endpoint de polling: devuelve mensajes con id mayor a `after`."""
    if requiere_login():
        return jsonify({"error": "no autenticado"}), 401

    after = request.args.get("after", 0, type=int)
    mensajes = cargar_json(CHAT_FILE, [])
    nuevos = [m for m in mensajes if m["id"] > after]
    return jsonify(nuevos)


@app.route("/chat/no-leidos")
def chat_no_leidos():
    """Cuenta mensajes que el usuario actual aún no ha visto (para el badge)."""
    if requiere_login():
        return jsonify({"error": "no autenticado"}), 401

    mensajes = cargar_json(CHAT_FILE, [])
    vistos = cargar_json(CHAT_SEEN_FILE, {})
    ultimo_visto = vistos.get(session["nombre"], 0)
    no_leidos = len([m for m in mensajes if m["id"] > ultimo_visto])
    return jsonify({"no_leidos": no_leidos})


@app.route("/chat/marcar-leido", methods=["POST"])
def chat_marcar_leido():
    """El chat abierto llama esto al recibir mensajes nuevos en vivo."""
    if requiere_login():
        return jsonify({"error": "no autenticado"}), 401

    mensajes = cargar_json(CHAT_FILE, [])
    if mensajes:
        vistos = cargar_json(CHAT_SEEN_FILE, {})
        vistos[session["nombre"]] = mensajes[-1]["id"]
        guardar_json(CHAT_SEEN_FILE, vistos)
    return jsonify({"ok": True})


# ---------- Calendario y reuniones ----------
def reuniones_de_usuario(nombre, admin, solo_futuras=True):
    reuniones = cargar_json(MEETINGS_FILE, [])
    hoy = datetime.now().strftime("%Y-%m-%d")
    visibles = [
        r for r in reuniones
        if admin or nombre in r.get("participantes", [])
    ]
    if solo_futuras:
        visibles = [r for r in visibles if r["fecha"] >= hoy]
    visibles.sort(key=lambda r: (r["fecha"], r.get("hora", "")))
    return visibles


@app.route("/calendario")
def calendario_vista():
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("Solo el equipo administrador gestiona el calendario")
        return redirect(url_for("menu"))

    hoy = datetime.now()
    anio = request.args.get("anio", hoy.year, type=int)
    mes = request.args.get("mes", hoy.month, type=int)
    if mes < 1:
        mes, anio = 12, anio - 1
    elif mes > 12:
        mes, anio = 1, anio + 1

    cal = calendar.Calendar(firstweekday=0)
    semanas = cal.monthdayscalendar(anio, mes)
    reuniones = cargar_json(MEETINGS_FILE, [])
    reuniones_por_dia = {}
    for r in reuniones:
        try:
            f = datetime.strptime(r["fecha"], "%Y-%m-%d")
        except ValueError:
            continue
        if f.year == anio and f.month == mes:
            reuniones_por_dia.setdefault(f.day, []).append(r)
    for dia in reuniones_por_dia:
        reuniones_por_dia[dia].sort(key=lambda r: r.get("hora", ""))

    nombre_mes = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ][mes - 1]

    usuarios = cargar_usuarios()
    proximas = reuniones_de_usuario(session["nombre"], True)[:8]

    return render_template(
        "calendario.html",
        **contexto_usuario(),
        anio=anio,
        mes=mes,
        nombre_mes=nombre_mes,
        semanas=semanas,
        reuniones_por_dia=reuniones_por_dia,
        usuarios=usuarios,
        proximas=proximas,
        hoy_dia=hoy.day if (hoy.year == anio and hoy.month == mes) else None,
    )


@app.route("/calendario/crear", methods=["POST"])
def calendario_crear():
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("No tienes permiso para crear reuniones")
        return redirect(url_for("menu"))

    fecha = request.form.get("fecha", "")
    titulo = request.form.get("titulo", "").strip()
    hora = request.form.get("hora", "")
    nota = request.form.get("nota", "").strip()
    participantes = request.form.getlist("participantes")

    if not fecha or not titulo:
        flash("Falta el título o la fecha de la reunión")
        return redirect(url_for("calendario_vista", anio=fecha[:4] if fecha else None))

    reuniones = cargar_json(MEETINGS_FILE, [])
    nuevo_id = (max([r["id"] for r in reuniones]) + 1) if reuniones else 1
    reuniones.append({
        "id": nuevo_id,
        "titulo": titulo,
        "fecha": fecha,
        "hora": hora,
        "nota": nota,
        "participantes": participantes,
        "creado_por": session["nombre"],
    })
    guardar_json(MEETINGS_FILE, reuniones)
    flash("Reunión programada")

    try:
        anio, mes = int(fecha[:4]), int(fecha[5:7])
    except (ValueError, IndexError):
        anio = mes = None
    return redirect(url_for("calendario_vista", anio=anio, mes=mes))


@app.route("/calendario/<int:reunion_id>/eliminar", methods=["POST"])
def calendario_eliminar(reunion_id):
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("No tienes permiso para eliminar reuniones")
        return redirect(url_for("menu"))

    reuniones = cargar_json(MEETINGS_FILE, [])
    reunion = next((r for r in reuniones if r["id"] == reunion_id), None)
    reuniones = [r for r in reuniones if r["id"] != reunion_id]
    guardar_json(MEETINGS_FILE, reuniones)
    flash("Reunión eliminada")

    if reunion:
        anio, mes = int(reunion["fecha"][:4]), int(reunion["fecha"][5:7])
        return redirect(url_for("calendario_vista", anio=anio, mes=mes))
    return redirect(url_for("calendario_vista"))


# ---------- Cuentas y roles ----------
ROLES_VALIDOS = ("Administrador", "Administradora", "Colaborador", "Colaboradora")


@app.route("/cuentas")
def cuentas_roles():
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("Solo el equipo administrador gestiona cuentas")
        return redirect(url_for("menu"))

    return render_template(
        "cuentas.html",
        **contexto_usuario(),
        usuarios=cargar_usuarios(),
        roles=ROLES_VALIDOS,
    )


@app.route("/cuentas/crear", methods=["POST"])
def cuentas_crear():
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("No tienes permiso para crear cuentas")
        return redirect(url_for("menu"))

    nombre = request.form.get("nombre", "").strip()
    password = request.form.get("password", "").strip()
    rol = request.form.get("rol", "Colaborador")
    puesto = request.form.get("puesto", "").strip()

    if not nombre or not password:
        flash("Falta el nombre o la contraseña")
        return redirect(url_for("cuentas_roles"))

    usuarios = cargar_usuarios()
    if any(u["nombre"].lower() == nombre.lower() for u in usuarios):
        flash("Ya existe una cuenta con ese nombre")
        return redirect(url_for("cuentas_roles"))

    usuarios.append({
        "nombre": nombre,
        "password": password,
        "rol": rol if rol in ROLES_VALIDOS else "Colaborador",
        "puesto": puesto,
    })
    guardar_usuarios(usuarios)
    flash(f"Cuenta de {nombre} creada")
    return redirect(url_for("cuentas_roles"))


@app.route("/cuentas/<nombre_usuario>/actualizar", methods=["POST"])
def cuentas_actualizar(nombre_usuario):
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("No tienes permiso para editar cuentas")
        return redirect(url_for("menu"))

    usuarios = cargar_usuarios()
    usuario = next((u for u in usuarios if u["nombre"] == nombre_usuario), None)
    if usuario is None:
        flash("Esa cuenta ya no existe")
        return redirect(url_for("cuentas_roles"))

    nuevo_rol = request.form.get("rol", usuario["rol"])
    nuevo_puesto = request.form.get("puesto", usuario.get("puesto", "")).strip()

    usuario["rol"] = nuevo_rol if nuevo_rol in ROLES_VALIDOS else usuario["rol"]
    usuario["puesto"] = nuevo_puesto

    guardar_usuarios(usuarios)
    if session["nombre"] == usuario["nombre"]:
        session["rol"] = usuario["rol"]
        session["puesto"] = usuario["puesto"]
    flash(f"Cuenta de {usuario['nombre']} actualizada")
    return redirect(url_for("cuentas_roles"))


@app.route("/cuentas/<nombre_usuario>/eliminar", methods=["POST"])
def cuentas_eliminar(nombre_usuario):
    if requiere_login():
        return redirect(url_for("index"))
    if not es_administrador():
        flash("No tienes permiso para eliminar cuentas")
        return redirect(url_for("menu"))

    if nombre_usuario == session["nombre"]:
        flash("No puedes eliminar tu propia cuenta")
        return redirect(url_for("cuentas_roles"))

    usuarios = cargar_usuarios()
    usuarios = [u for u in usuarios if u["nombre"] != nombre_usuario]
    guardar_usuarios(usuarios)
    flash("Cuenta eliminada")
    return redirect(url_for("cuentas_roles"))


# ---------- Perfil ----------
@app.route("/perfil", methods=["GET", "POST"])
def perfil():
    if requiere_login():
        return redirect(url_for("index"))

    usuarios = cargar_usuarios()
    usuario = next((u for u in usuarios if u["nombre"] == session["nombre"]), None)

    if usuario is None:
        session.clear()
        return redirect(url_for("index"))

    if request.method == "POST":
        nuevo_nombre = request.form.get("nombre", "").strip()
        nueva_password = request.form.get("password", "").strip()
        confirmar_password = request.form.get("confirmar_password", "").strip()
        foto_file = request.files.get("foto")

        # Validar nombre duplicado (si cambió)
        if nuevo_nombre and nuevo_nombre.lower() != usuario["nombre"].lower():
            if any(u["nombre"].lower() == nuevo_nombre.lower() for u in usuarios):
                flash("Ese nombre ya está en uso")
                return redirect(url_for("perfil"))
            usuario["nombre"] = nuevo_nombre
            session["nombre"] = nuevo_nombre

        # Validar contraseña
        if nueva_password or confirmar_password:
            if nueva_password != confirmar_password:
                flash("Las contraseñas no coinciden")
                return redirect(url_for("perfil"))
            if len(nueva_password) < 6:
                flash("La contraseña debe tener al menos 6 caracteres")
                return redirect(url_for("perfil"))
            usuario["password"] = nueva_password

        # Foto de perfil
        if foto_file and foto_file.filename:
            if archivo_permitido(foto_file.filename):
                ext = foto_file.filename.rsplit(".", 1)[1].lower()
                nombre_archivo = f"{uuid.uuid4().hex}.{ext}"
                foto_file.save(os.path.join(UPLOAD_FOLDER, nombre_archivo))
                usuario["foto"] = nombre_archivo
            else:
                flash("Formato de imagen no permitido (usa png, jpg o webp)")
                return redirect(url_for("perfil"))

        guardar_usuarios(usuarios)
        flash("Perfil actualizado")
        return redirect(url_for("perfil"))

    return render_template(
        "perfil.html",
        **contexto_usuario(),
    )


if __name__ == "__main__":
    app.run(debug=True)
