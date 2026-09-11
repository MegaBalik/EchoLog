from django.contrib import admin
from .models import Batch, Contact, GmailSyncState, Recipient


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'email', 'country', 'segment', 'do_not_contact', 'bounced')
    search_fields = ('organization_name', 'email', 'country', 'segment')
    list_filter = ('country', 'segment', 'do_not_contact', 'bounced')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_at', 'started_at', 'daily_limit')
    list_filter = ('status',)
    search_fields = ('name', 'subject')


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ('contact', 'batch', 'status', 'hope', 'sent_at', 'replied_at')
    list_filter = ('status', 'hope', 'batch', 'contact__country')
    search_fields = ('contact__organization_name', 'contact__email', 'batch__name')
    raw_id_fields = ('contact', 'batch')

admin.site.register(GmailSyncState)
