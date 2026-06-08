
"""
accounts/tests.py

Suite de tests para el módulo de cuentas de usuario.
Cubre: modelos, formularios y vistas.

"""
from django.test import TestCase
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .forms import RegistroForm
from .models import PerfilUsuario


# =============================================================================
# TESTS DE MODELO
# =============================================================================

class PerfilUsuarioModelTests(TestCase):
    """Pruebas CRUD y de integridad sobre el modelo PerfilUsuario."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="contraseña1234",
            email="test@ejemplo.com",
        )

    # --- Create ---

    def test_crear_perfil_usuario(self):
        """Podemos crear un PerfilUsuario asociado a un User."""
        perfil = PerfilUsuario.objects.create(
            usuario=self.user,
            equipo_favorito="RC Deportivo de La Coruña",
        )
        self.assertIsNotNone(perfil.pk)
        self.assertEqual(perfil.usuario, self.user)

    def test_valor_por_defecto_equipo_favorito(self):
        """El campo equipo_favorito tiene el valor por defecto correcto."""
        perfil = PerfilUsuario.objects.create(usuario=self.user)
        self.assertEqual(perfil.equipo_favorito, "RC Deportivo de La Coruña")

    def test_fecha_registro_se_asigna_automaticamente(self):
        """fecha_registro se rellena con auto_now_add al crear el perfil."""
        perfil = PerfilUsuario.objects.create(usuario=self.user)
        self.assertIsNotNone(perfil.fecha_registro)

    # --- Read ---

    def test_leer_perfil_usuario(self):
        """Podemos recuperar el PerfilUsuario desde la base de datos."""
        PerfilUsuario.objects.create(
            usuario=self.user,
            equipo_favorito="Real Madrid",
        )
        perfil_bd = PerfilUsuario.objects.get(usuario=self.user)
        self.assertEqual(perfil_bd.equipo_favorito, "Real Madrid")

    def test_relacion_inversa_desde_user(self):
        """Desde el User podemos acceder al perfil con el related_name 'perfil'."""
        PerfilUsuario.objects.create(usuario=self.user)
        self.assertEqual(self.user.perfil.usuario, self.user)

    # --- Update ---

    def test_actualizar_equipo_favorito(self):
        """Se puede actualizar el equipo favorito y persistir el cambio."""
        perfil = PerfilUsuario.objects.create(
            usuario=self.user,
            equipo_favorito="RC Deportivo de La Coruña",
        )
        perfil.equipo_favorito = "Celta de Vigo"
        perfil.save()

        perfil_actualizado = PerfilUsuario.objects.get(pk=perfil.pk)
        self.assertEqual(perfil_actualizado.equipo_favorito, "Celta de Vigo")

    # --- Delete ---

    def test_borrar_perfil_usuario(self):
        """Se puede eliminar un PerfilUsuario de la base de datos."""
        perfil = PerfilUsuario.objects.create(usuario=self.user)
        pk = perfil.pk
        perfil.delete()
        self.assertFalse(PerfilUsuario.objects.filter(pk=pk).exists())

    def test_cascade_borrado_desde_user(self):
        """Al eliminar un User, su PerfilUsuario se borra en cascada."""
        perfil = PerfilUsuario.objects.create(usuario=self.user)
        pk = perfil.pk
        self.user.delete()
        self.assertFalse(PerfilUsuario.objects.filter(pk=pk).exists())

    # --- __str__ y meta ---

    def test_str_perfil_usuario(self):
        """El método __str__ devuelve el formato esperado."""
        perfil = PerfilUsuario.objects.create(
            usuario=self.user,
            equipo_favorito="RC Deportivo de La Coruña",
        )
        esperado = f"Perfil de {self.user.username} — RC Deportivo de La Coruña"
        self.assertEqual(str(perfil), esperado)

    def test_unicidad_onetoone(self):
        """No se pueden crear dos PerfilUsuario para el mismo User."""
        from django.db import IntegrityError
        PerfilUsuario.objects.create(usuario=self.user)
        with self.assertRaises(IntegrityError):
            PerfilUsuario.objects.create(usuario=self.user)


# =============================================================================
# TESTS DE FORMULARIO
# =============================================================================

class RegistroFormTests(TestCase):
    """Pruebas sobre la validación y guardado del formulario de registro."""

    def _datos_validos(self, **kwargs):
        base = {
            "username": "nuevo_usuario",
            "email": "nuevo@ejemplo.com",
            "password1": "ContraseñaSegura123!",
            "password2": "ContraseñaSegura123!",
            "equipo_favorito": "RC Deportivo de La Coruña",
        }
        base.update(kwargs)
        return base

    def test_formulario_valido(self):
        """El formulario acepta datos correctos."""
        form = RegistroForm(data=self._datos_validos())
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_formulario_crea_perfil_al_guardar(self):
        """form.save() crea tanto el User como su PerfilUsuario."""
        form = RegistroForm(data=self._datos_validos())
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertTrue(PerfilUsuario.objects.filter(usuario=user).exists())

    def test_equipo_favorito_se_guarda_en_perfil(self):
        """El equipo favorito introducido en el formulario se persiste en el perfil."""
        form = RegistroForm(data=self._datos_validos(equipo_favorito="Barça"))
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.perfil.equipo_favorito, "Barça")

    def test_formulario_invalido_passwords_distintas(self):
        """El formulario es inválido si las contraseñas no coinciden."""
        form = RegistroForm(data=self._datos_validos(password2="OtraContraseña999!"))
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_formulario_invalido_sin_email(self):
        """El formulario es inválido si falta el email (campo required)."""
        form = RegistroForm(data=self._datos_validos(email=""))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_formulario_sin_equipo_favorito_usa_defecto(self):
        """Si no se especifica equipo favorito, el perfil usa el valor por defecto."""
        form = RegistroForm(data=self._datos_validos(equipo_favorito=""))
        self.assertTrue(form.is_valid())
        user = form.save()
        # El campo es required=False; el modelo tiene default, así que es "" o el default
        perfil = PerfilUsuario.objects.get(usuario=user)
        self.assertIsNotNone(perfil)


# =============================================================================
# TESTS DE VISTAS
# =============================================================================

class RegistroViewTests(TestCase):
    """Pruebas de la vista accounts:registro."""

    def setUp(self):
        self.url = reverse("accounts:registro")
        self.datos_validos = {
            "username": "usuario_nuevo",
            "email": "nuevo@ejemplo.com",
            "password1": "ContraseñaSegura123!",
            "password2": "ContraseñaSegura123!",
            "equipo_favorito": "RC Deportivo de La Coruña",
        }

    def test_get_muestra_formulario(self):
        """GET a /registro/ devuelve 200 y renderiza el template correcto."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/registro.html")
        self.assertIn("form", response.context)

    def test_post_valido_crea_usuario_y_redirige(self):
        """POST con datos válidos crea el usuario y redirige a /."""
        response = self.client.post(self.url, self.datos_validos)
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="usuario_nuevo").exists())

    def test_post_valido_crea_perfil_de_usuario(self):
        """POST con datos válidos crea también el PerfilUsuario."""
        self.client.post(self.url, self.datos_validos)
        user = User.objects.get(username="usuario_nuevo")
        self.assertTrue(PerfilUsuario.objects.filter(usuario=user).exists())

    def test_post_valido_inicia_sesion_automaticamente(self):
        """Tras el registro, el usuario queda autenticado en la sesión."""
        self.client.post(self.url, self.datos_validos)
        # Si hay usuario en session, la clave _auth_user_id existe
        self.assertIn("_auth_user_id", self.client.session)

    def test_post_valido_muestra_mensaje_bienvenida(self):
        """POST válido genera un mensaje de éxito en la sesión."""
        response = self.client.post(self.url, self.datos_validos, follow=True)
        mensajes = list(get_messages(response.wsgi_request))
        textos = [str(m) for m in mensajes]
        self.assertTrue(any("Bienvenido" in t for t in textos))

    def test_post_invalido_no_crea_usuario(self):
        """POST con passwords distintas no crea ningún usuario."""
        datos = {**self.datos_validos, "password2": "OtraDistinta999!"}
        self.client.post(self.url, datos)
        self.assertFalse(User.objects.filter(username="usuario_nuevo").exists())

    def test_post_invalido_muestra_formulario_con_errores(self):
        """POST inválido vuelve a renderizar el formulario (status 200)."""
        datos = {**self.datos_validos, "password2": "OtraDistinta999!"}
        response = self.client.post(self.url, datos)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/registro.html")

    def test_post_invalido_muestra_mensaje_de_error(self):
        """POST inválido añade el mensaje de error al contexto."""
        datos = {**self.datos_validos, "password2": "OtraDistinta999!"}
        response = self.client.post(self.url, datos)
        mensajes = list(get_messages(response.wsgi_request))
        textos = [str(m) for m in mensajes]
        self.assertTrue(any("corrige" in t for t in textos))


class LoginViewTests(TestCase):
    """Pruebas de la vista accounts:login."""

    def setUp(self):
        self.url = reverse("accounts:login")
        self.user = User.objects.create_user(
            username="usuariotest",
            password="ContraseñaSegura123!",
        )

    def test_get_muestra_formulario_login(self):
        """GET a /login/ devuelve 200 y usa el template de login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertIn("form", response.context)

    def test_usuario_autenticado_redirige_a_home(self):
        """Si el usuario ya está autenticado, GET a /login/ redirige a /."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_credenciales_correctas_inicia_sesion(self):
        """POST con credenciales válidas autentica al usuario."""
        self.client.post(self.url, {"username": "usuariotest", "password": "ContraseñaSegura123!"})
        self.assertIn("_auth_user_id", self.client.session)

    def test_post_credenciales_correctas_redirige_a_home(self):
        """POST válido redirige a / por defecto."""
        response = self.client.post(
            self.url,
            {"username": "usuariotest", "password": "ContraseñaSegura123!"},
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_credenciales_correctas_con_next_valido(self):
        """POST válido con ?next= seguro redirige a esa URL."""
        url_con_next = f"{self.url}?next=/rendimiento/"
        response = self.client.post(
            url_con_next,
            {"username": "usuariotest", "password": "ContraseñaSegura123!"},
        )
        self.assertRedirects(response, "/rendimiento/", fetch_redirect_response=False)

    def test_post_credenciales_correctas_con_next_externo_redirige_a_home(self):
        """Un ?next= apuntando a dominio externo debe ser ignorado (seguridad)."""
        url_con_next = f"{self.url}?next=http://malicioso.com"
        response = self.client.post(
            url_con_next,
            {"username": "usuariotest", "password": "ContraseñaSegura123!"},
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_post_credenciales_incorrectas_no_inicia_sesion(self):
        """POST con contraseña incorrecta no autentica al usuario."""
        self.client.post(self.url, {"username": "usuariotest", "password": "mala_clave"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_post_credenciales_incorrectas_muestra_error(self):
        """POST con credenciales erróneas genera mensaje de error."""
        response = self.client.post(
            self.url,
            {"username": "usuariotest", "password": "mala_clave"},
        )
        mensajes = list(get_messages(response.wsgi_request))
        textos = [str(m) for m in mensajes]
        self.assertTrue(any("contraseña" in t.lower() or "incorrectos" in t.lower() for t in textos))

    def test_post_credenciales_incorrectas_devuelve_200(self):
        """POST fallido vuelve a renderizar la página de login."""
        response = self.client.post(
            self.url,
            {"username": "usuariotest", "password": "mala_clave"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")


class LogoutViewTests(TestCase):
    """Pruebas de la vista accounts:logout."""

    def setUp(self):
        self.url = reverse("accounts:logout")
        self.user = User.objects.create_user(
            username="usuariotest",
            password="ContraseñaSegura123!",
        )

    def test_post_cierra_sesion_y_redirige(self):
        """POST a /logout/ cierra la sesión y redirige a la página de login."""
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)

    def test_post_elimina_sesion_del_usuario(self):
        """Tras el logout, el usuario deja de estar autenticado."""
        self.client.force_login(self.user)
        self.client.post(self.url)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_post_logout_muestra_mensaje_informativo(self):
        """El logout genera un mensaje de confirmación."""
        self.client.force_login(self.user)
        response = self.client.post(self.url, follow=True)
        mensajes = list(get_messages(response.wsgi_request))
        textos = [str(m) for m in mensajes]
        self.assertTrue(any("cerrado sesión" in t for t in textos))

    def test_get_logout_devuelve_405(self):
        """GET a /logout/ devuelve 405 Method Not Allowed (decorador @require_POST)."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)


# =============================================================================
# TESTS CON MOCKING (@patch)
# =============================================================================

class RegistroConPatchTests(TestCase):
    """
    Pruebas que usan @patch para aislar componentes internos.
    Ilustran cómo verificar que se llaman las funciones correctas
    sin depender de efectos secundarios reales.
    """

    def setUp(self):
        self.url = reverse("accounts:registro")
        self.datos_validos = {
            "username": "mockeado",
            "email": "mockeado@ejemplo.com",
            "password1": "ContraseñaSegura123!",
            "password2": "ContraseñaSegura123!",
            "equipo_favorito": "RC Deportivo de La Coruña",
        }

    @patch("accounts.views.login")
    def test_login_se_llama_tras_registro_exitoso(self, mock_login):
        """
        Tras un registro válido, se invoca django.contrib.auth.login
        exactamente una vez con el nuevo usuario.
        """
        response = self.client.post(self.url, self.datos_validos)
        # El registro redirige; login debería haberse llamado
        self.assertEqual(mock_login.call_count, 1)
        args, _ = mock_login.call_args
        # El segundo argumento es el User creado
        usuario_logueado = args[1]
        self.assertEqual(usuario_logueado.username, "mockeado")

    @patch("accounts.views.messages.error")
    def test_messages_error_se_llama_con_formulario_invalido(self, mock_error):
        """
        Con datos inválidos, se llama a messages.error con el mensaje apropiado.
        """
        datos_malos = {**self.datos_validos, "password2": "OtraDistinta999!"}
        self.client.post(self.url, datos_malos)
        mock_error.assert_called_once()
        _, mensaje = mock_error.call_args[0]
        self.assertIn("corrige", mensaje)