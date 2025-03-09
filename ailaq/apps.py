from django.apps import AppConfig

class AilaqConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ailaq'

    def ready(self):
        import ailaq.signals