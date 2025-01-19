from django.contrib.auth import get_user_model
from rest_framework import serializers
from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel, \
    Review

CustomUser = get_user_model()

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(read_only=True)  # role доступно только для чтения

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'is_psychologist', 'role']

    def create(self, validated_data):
        is_psychologist = validated_data.get('is_psychologist', False)
        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            is_psychologist=is_psychologist,
        )

        if is_psychologist:
            # Создаём заявку со статусом 'PENDING'
            PsychologistApplication.objects.create(user=user, status='PENDING')
            # Создаём профиль с is_verified=False, is_in_catalog=False
            PsychologistProfile.objects.create(user=user, is_verified=False, is_in_catalog=False)

        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        user = get_user_model().objects.filter(email=email).first()
        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid credentials")

        return data

class PsychologistProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistProfile
        fields = '__all__'

class PsychologistApplicationSerializer(serializers.ModelSerializer):
    level = serializers.StringRelatedField()

    class Meta:
        model = PsychologistApplication
        fields = '__all__'

class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = '__all__'

class PsychologistLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistLevel
        fields = '__all__'

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = "__all__"