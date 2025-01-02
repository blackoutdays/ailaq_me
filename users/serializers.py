from rest_framework import serializers
from .models import (
    CustomUser, ClientProfile, PsychologistProfile, UserLevel,
    PsychologistApplication, RequestCatalog, PsychologistRequestBalance,
    RequestPurchase, Schedule, Session, Feedback, Notification, MessageLog,
    Bot, ActionLog
)

# Сериализатор для CustomUser
class CustomUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = '__all__'  # Выберите поля, которые нужно отображать

# Сериализатор для ClientProfile
class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = '__all__'

# Сериализатор для PsychologistProfile
class PsychologistProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistProfile
        fields = '__all__'

# Сериализатор для UserLevel
class UserLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserLevel
        fields = '__all__'

# Сериализатор для PsychologistApplication
class PsychologistApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = '__all__'

# Сериализатор для RequestCatalog
class RequestCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestCatalog
        fields = '__all__'

# Сериализатор для PsychologistRequestBalance
class PsychologistRequestBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistRequestBalance
        fields = '__all__'

# Сериализатор для RequestPurchase
class RequestPurchaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestPurchase
        fields = '__all__'

# Сериализатор для Schedule
class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = '__all__'

# # Сериализатор для Session
# class SessionSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Session
#         fields = '__all__'

# Сериализатор для Feedback
class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = '__all__'

# Сериализатор для Notification
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'

# Сериализатор для MessageLog
class MessageLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageLog
        fields = '__all__'

# Сериализатор для Bot
class BotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bot
        fields = '__all__'

# Сериализатор для ActionLog
class ActionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionLog
        fields = '__all__'



# Сериализатор для Session
class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)