#tasks.py
from .models import PsychologistLevel, PsychologistApplication

def check_psychologist_level(user):
    """Проверка уровня психолога в зависимости от количества просроченных заявок"""
    profile = user.psychologist_profile
    level = PsychologistLevel.objects.get(name='LEVEL_1') if profile.expired_applications > 0 else \
        PsychologistLevel.objects.get(name='LEVEL_2')

    profile.level = level
    profile.save()

def check_and_update_applications():
    """Функция для проверки просроченных заявок и их статуса"""
    applications = PsychologistApplication.objects.all()
    for application in applications:
        if application.is_expired():
            application.status = 'EXPIRED'
            application.save()
