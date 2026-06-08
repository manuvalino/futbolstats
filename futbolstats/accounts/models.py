"""
accounts/models.py
Perfil de usuario extendido.
"""

from django.db import models
from django.contrib.auth.models import User


class PerfilUsuario(models.Model):
    """Extiende el User de Django con preferencias adicionales."""

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    equipo_favorito = models.CharField(
        max_length=100,
        default="RC Deportivo de La Coruña",
        help_text="Nombre del equipo favorito del usuario",
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"

    def __str__(self):
        return f"Perfil de {self.usuario.username} — {self.equipo_favorito}"
