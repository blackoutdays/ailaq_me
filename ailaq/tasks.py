#tasks.py
from . import models
from .models import PsychologistApplication, PsychologistProfile, PsychologistLevel
from datetime import date

def check_psychologist_level(user):
    """
    Проверка уровня психолога на основе количества просроченных заявок.
    """
    profile = user.psychologist_profile
    expired_count = PsychologistApplication.objects.filter(
        user=user, status='EXPIRED'
    ).count()

    if expired_count > 0:
        new_level = PsychologistLevel.objects.get(name='LEVEL_1')
    else:
        new_level = PsychologistLevel.objects.get(name='LEVEL_2')

    profile.level = new_level
    profile.save()


def check_and_update_applications():
    """ Проверка просроченных заявок. """
    expiry_date = models.DateField(null=True, blank=True)
    applications = PsychologistApplication.objects.filter(status='PENDING')
    for application in applications:
        if application.expiry_date and application.expiry_date < date.today():
            application.status = 'EXPIRED'
            application.save()