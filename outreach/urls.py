from django.urls import path
from . import views

app_name = 'outreach'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('senders/new/', views.sender_create, name='sender_create'),
    path('senders/<int:pk>/connect/', views.sender_google_connect, name='sender_google_connect'),
    path('batches/new/', views.batch_create, name='batch_create'),
    path('batches/<int:pk>/', views.batch_detail, name='batch_detail'),
    path('batches/<int:pk>/start/', views.batch_start, name='batch_start'),
    path('batches/<int:pk>/pause/', views.batch_pause, name='batch_pause'),
    path('batches/<int:pk>/message/', views.batch_edit_message, name='batch_edit_message'),
    path('batches/<int:pk>/delete/', views.batch_delete, name='batch_delete'),
    path('batches/<int:pk>/test-send/', views.batch_test_send, name='batch_test_send'),
    path('report/', views.report, name='report'),
    path('report/export/', views.report_export, name='report_export'),
    path('recipient/<int:pk>/update/', views.recipient_update, name='recipient_update'),
    path('recipient/<int:pk>/suppress/', views.recipient_suppress, name='recipient_suppress'),
    path('recipient/<int:pk>/bounced/', views.recipient_mark_bounced, name='recipient_mark_bounced'),
    # Legacy single-account entry point kept as a convenience redirect.
    path('google/connect/', views.google_connect, name='google_connect'),
    path('google/oauth/callback/', views.google_callback, name='google_callback'),
]
