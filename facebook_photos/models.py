# -*- coding: utf-8 -*-
import logging
import re
import time
from datetime import datetime

from django.db import models, transaction
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.utils import timezone
from django.utils.translation import ugettext as _

from facebook_api import fields
from facebook_api.models import FacebookGraphModel, FacebookGraphManager #
from facebook_api.utils import graph
from facebook_users.models import User
from facebook_pages.models import Page
from facebook_posts.models import get_or_create_from_small_resource
from m2m_history.fields import ManyToManyHistoryField

log = logging.getLogger('facebook_photos')

ALBUM_TYPE_CHOCIES = (
    (0, u'Все пользователи'),
    (1, u'Только друзья'),
    (2, u'Друзья и друзья друзей'),
    (3, u'Только я')
)


# TODO: in development
class FBModelManager(models.Manager):
    def get_by_natural_key(self, graph_id):
        return self.get(graph_id=graph_id)



class AlbumRemoteManager(FacebookGraphManager):

    #@transaction.commit_on_success
    def fetch_by_page(self, page, limit=1000, until=None, since=None, **kwargs):

        kwargs.update({
            'limit': int(limit),
        })


        for field in ['until', 'since']:
            value = locals()[field]
            if isinstance(value, datetime):
                kwargs[field] = int(time.mktime(value.timetuple()))
            elif value is not None:
                try:
                    kwargs[field] = int(value)
                except TypeError:
                    raise ValueError('Wrong type of argument %s: %s' % (field, type(value)))


        ids = []
        response = graph("%s/albums/" % page.graph_id, **kwargs)
        #log.debug('response objects count - %s' % len(response.data))

        for resource in response.data:
            instance = self.get_or_create_from_resource(resource)
            ids += [instance.pk]

        return Album.objects.filter(pk__in=ids)



class PhotoRemoteManager(FacebookGraphManager):

    #@transaction.commit_on_success
    def fetch_by_album(self, album, limit=100, offset=0, until=None, since=None, **kwargs):

        kwargs.update({
            'limit': int(limit),
            'offset': int(offset),
        })

        for field in ['until', 'since']:
            value = locals()[field]
            if isinstance(value, datetime):
                kwargs[field] = int(time.mktime(value.timetuple()))
            elif value is not None:
                try:
                    kwargs[field] = int(value)
                except TypeError:
                    raise ValueError('Wrong type of argument %s: %s' % (field, type(value)))


        ids = []
        response = graph("%s/photos" % album.pk, **kwargs)
        #log.debug('response objects count - %s' % len(response.data))

        extra_fields = {"album_id": album.pk }
        for resource in response.data:
            instance = self.get_or_create_from_resource(resource, extra_fields)
            ids += [instance.pk]

        return Photo.objects.filter(pk__in=ids)



class FacebookGraphIDModel(FacebookGraphModel):

    graph_id = models.BigIntegerField(u'ID', primary_key=True, unique=True, max_length=100, help_text=_('Unique graph ID'))

    def get_url(self, slug=None):
        if slug is None:
            slug = self.graph_id
        return 'http://facebook.com/%s' % slug

    def _substitute(self, old_instance):
        return None

    @property
    def id(self):
        return self.graph_id # return self.pk

    class Meta:
        abstract = True



class AuthorMixin(models.Model):
    author_json = fields.JSONField(null=True, help_text='Information about the user who posted the message') # object containing the name and Facebook id of the user who posted the message

    author_content_type = models.ForeignKey(ContentType, null=True) # , related_name='facebook_albums'
    author_id = models.PositiveIntegerField(null=True, db_index=True)
    author = generic.GenericForeignKey('author_content_type', 'author_id')

    def parse(self, response):
        if 'from' in response:
            response['author_json'] = response.pop('from')

        super(AuthorMixin, self).parse(response)

        if self.author is None and self.author_json:
            self.author = get_or_create_from_small_resource(self.author_json)

    class Meta:
        abstract = True



class LikesCountMixin(models.Model):
    likes_count = models.IntegerField(null=True, help_text='The number of comments of this item')

    class Meta:
        abstract = True

    def parse(self, response):
        if 'likes' in response:
            response['likes_count'] = len(response['likes']["data"])
        super(LikesCountMixin, self).parse(response)



class CommentsCountMixin(models.Model):
    comments_count = models.IntegerField(null=True, help_text='The number of comments of this item')

    class Meta:
        abstract = True

    def parse(self, response):
        if 'comments' in response:
            response['comments_count'] = len(response['comments']["data"])
        super(CommentsCountMixin, self).parse(response)



class Album(AuthorMixin, LikesCountMixin, CommentsCountMixin, FacebookGraphIDModel):
    #remote_pk_field = 'aid'
    #slug_prefix = 'album'


    can_upload = models.BooleanField()
    photos_count = models.PositiveIntegerField(u'Кол-во фотографий', default=0)
    cover_photo = models.BigIntegerField(null=True)
    link = models.URLField(max_length=255)
    location = models.CharField(max_length='200')
    place = models.CharField(max_length='200') # page
    privacy = models.CharField(max_length='200')
    type = models.CharField(max_length='200')

    # TODO: migrate to ContentType framework, remove vkontakte_users and vkontakte_groups dependencies
    #owner = models.ForeignKey(User, verbose_name=u'Владелец альбома', null=True, related_name='photo_albums')
    #group = models.ForeignKey(Group, verbose_name=u'Группа альбома', null=True, related_name='photo_albums')

    name = models.CharField(max_length='200')
    description = models.TextField()

    created_time = models.DateTimeField(null=True, db_index=True)
    updated_time = models.DateTimeField(null=True, db_index=True)


    objects = models.Manager()
    remote = AlbumRemoteManager()
#    remote = AlbumRemoteManager(remote_pk=('remote_id',), methods={
#        'get': 'getAlbums',
##        'edit': 'editAlbum',
#    })

#    @property
#    def from(self):
#        return self.owner

    class Meta:
        verbose_name = u'Альбом фотографий Facebook'
        verbose_name_plural = u'Альбомы фотографий Facebook'

    def __unicode__(self):
        return self.name


#    @transaction.commit_on_success
    def fetch_photos(self, **kwargs):
        return Photo.remote.fetch_by_album(album=self, **kwargs)

    def parse(self, response):
        response['photos_count'] = response.get("count", 0)
        super(Album, self).parse(response)



class Photo(AuthorMixin, LikesCountMixin, CommentsCountMixin, FacebookGraphIDModel):
    album = models.ForeignKey(Album, verbose_name=u'Альбом', related_name='photos', null=True)

    # TODO: switch to ContentType, remove owner and group foreignkeys
    #owner = models.ForeignKey(User, verbose_name=u'Владелец фотографии', null=True, related_name='photos')
    #group = models.ForeignKey(Group, verbose_name=u'Группа фотографии', null=True, related_name='photos')

    #user = models.ForeignKey(User, verbose_name=u'Автор фотографии', null=True, related_name='photos_author')
    link = models.URLField(max_length=255)
    picture = models.URLField(max_length=255) #Link to the 100px wide representation of this photo
    source = models.URLField(max_length=255)

    name = models.CharField(max_length=200, blank=True)
    place = models.CharField(max_length=200, blank=True) # Page

    width = models.PositiveIntegerField(null=True)
    height = models.PositiveIntegerField(null=True)

#    likes_count = models.PositiveIntegerField(u'Лайков', default=0)
#    comments_count = models.PositiveIntegerField(u'Комментариев', default=0)
#    actions_count = models.PositiveIntegerField(u'Комментариев', default=0)
#    tags_count = models.PositiveIntegerField(u'Тегов', default=0)
#
#    like_users = models.ManyToManyField(User, related_name='like_photos')

    created_time = models.DateTimeField(db_index=True)
    updated_time = models.DateTimeField(db_index=True)


    objects = models.Manager()
    remote = PhotoRemoteManager()
#    remote = PhotoRemoteManager(remote_pk=('remote_id',), methods={
#        'get': 'get',
#    })


    class Meta:
        verbose_name = u'Фотография Facebook'
        verbose_name_plural = u'Фотографии Facebook'


    def parse(self, response):
        if 'album' in response:
            print response["album"]
            self.album = response["album"]

        super(Photo, self).parse(response)


#
#        # counters
#        for field_name in ['likes','comments','tags']:
#            if field_name in response and 'count' in response[field_name]:
#                setattr(self, '%s_count' % field_name, response[field_name]['count'])
#
#        self.actions_count = self.likes_count + self.comments_count
#
#        if 'user_id' in response:
#            self.user = User.objects.get_or_create(remote_id=response['user_id'])[0]
#
#        try:
#            self.album = Album.objects.get(remote_id=self.get_remote_id(response['aid']))
#        except Album.DoesNotExist:
#            raise Exception('Impossible to save photo for unexisted album %s' % (self.get_remote_id(response['aid']),))
#
#    def fetch_comments_parser(self):
#        '''
#        Fetch total ammount of comments
#        TODO: implement fetching comments
#        '''
#        post_data = {
#            'act':'photo_comments',
#            'al': 1,
#            'offset': 0,
#            'photo': self.remote_id,
#        }
#        #parser = VkontaktePhotosParser().request('/al_photos.php', data=post_data)
#
#        self.comments_count = len(parser.content_bs.findAll('div', {'class': 'clear_fix pv_comment '}))
#        self.save()
#
#    def fetch_likes_parser(self):
#        '''
#        Fetch total ammount of likes
#        TODO: implement fetching users who likes
#        '''
#        post_data = {
#            'act':'a_get_stats',
#            'al': 1,
#            'list': 'album%s' % self.album.remote_id,
#            'object': 'photo%s' % self.remote_id,
#        }
#        #parser = VkontaktePhotosParser().request('/like.php', data=post_data)
#
#        values = re.findall(r'value="(\d+)"', parser.html)
#        if len(values):
#            self.likes_count = int(values[0])
#            self.save()
#
#    @transaction.commit_on_success
#    def fetch_likes(self, *args, **kwargs):
#
##        kwargs['offset'] = int(kwargs.pop('offset', 0))
#        kwargs['likes_type'] = 'photo'
#        kwargs['item_id'] = self.remote_id.split('_')[1]
#        kwargs['owner_id'] = self.group.remote_id
#        if isinstance(self.group, Group):
#            kwargs['owner_id'] *= -1
#
#        log.debug('Fetching likes of %s %s of owner "%s"' % (self._meta.module_name, self.remote_id, self.group))
#
#        users = User.remote.fetch_instance_likes(self, *args, **kwargs)
#
#        # update self.likes
#        self.likes_count = self.like_users.count()
#        self.save()
#
#        return users
#
#    @transaction.commit_on_success
#    def fetch_comments(self, *args, **kwargs):
#        return Comment.remote.fetch_photo(photo=self, *args, **kwargs)



#import signals
