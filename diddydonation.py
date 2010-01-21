import os
import cgi
import hashlib
import Cookie
import logging
import datetime

from google.appengine.api import users

from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

_DEBUG = False


############## Models ###################

class Campaign(db.Model):
    link        = db.LinkProperty(required=True)
    beneficiary = db.UserProperty()
    date        = db.DateTimeProperty(auto_now_add=True)
    count       = db.IntegerProperty(required=True, default=0)

class Person(db.Model):
    donator   = db.UserProperty(required=True)
    hashedkey = db.StringProperty()
    def put(self):
        if self.hashedkey is None:
            if self.is_saved():
                key = self.key()
            else:
                key = db.Model.put(self)
        self.hashedkey = hashlib.sha1(str(key)).hexdigest()
        assert self.hashedkey
        return db.Model.put(self)

class PennyDonation(db.Model):
    donator   = db.ReferenceProperty(Person,required=True)
    campaign  = db.ReferenceProperty(Campaign,required=True)
    date_list = db.ListProperty(datetime.datetime)
    date      = db.DateTimeProperty(auto_now=True)

############# Utils #####################
def bookmarklet(host, person):
  js = """
javascript:
var d=document,w=window,f='http://%s/donate',l=d.location,e=encodeURIComponent,p='?bookmarklet=true&v=1&k=%s&link='+e(l.href),u=f+p;var a=function(){if(!w.open(u,'t','toolbar=0,resizable=0,status=1,width=250,height=150'))l.href=u;};if(/Firefox/.test(navigator.userAgent))setTimeout(a,0);else a();void(0)
""" % (host,person.hashedkey)
  return js.replace("\n",'')


############# Base Handler ##############
class BaseHandler(webapp.RequestHandler):

    logged_in_person = None

    def get_or_create_logged_in_person(self):
        if self.logged_in_person:
            return self.logged_in_person
        me = users.get_current_user()
        if me:
            persons = Person.gql("WHERE donator = :1",me)
            if persons.count() == 0:
                # Save new Person to datastore (auto-generate a hash)
                p = Person(donator=users.get_current_user())
                p.put()
            elif persons.count() == 1:
                p = persons[0]
            else:
                logging.error('Found multiple People with the same hashedkey.')
            self.logged_in_person = p
            return self.logged_in_person
        return None

    def render(self, template_name, extra_values={}):

        lip = users.get_current_user()

        if lip:
            userid = lip.user_id()
        else:
            userid = None

        values = {
        'request': self.request,
        'user': lip,
        'userid': userid,
        'lip': self.get_or_create_logged_in_person(),
        'login_url': users.create_login_url('/home'),
        'logout_url': users.create_logout_url('http://%s/' % (self.request.host,)),
        'debug': self.request.get('deb')}

        values.update(extra_values)
        cwd = os.path.dirname(__file__)
        path = os.path.join(cwd, 'templates', template_name + '.html')
        logging.debug(path)
        self.response.out.write(template.render(path, values, debug=_DEBUG))

    def show_main_page(self, error_msg=None):
        """Do an internal (non-302) redirect to the front page.

        Preserves the user agent's requested URL.
        """
        page = MainPage()
        page.request = self.request
        page.response = self.response
        page.get(error_msg)

############## Handlers #################
class MainPage(BaseHandler):
    def get(self, error_msg=None):
        campaigns = Campaign.gql("ORDER BY date DESC LIMIT 7")
        self.render('index', {'campaigns': campaigns,'error_msg': error_msg})

class HomePage(BaseHandler):
    def get(self):
        if users.get_current_user():
            me = self.get_or_create_logged_in_person()
            self.render('home',{'bookmarklet': bookmarklet(self.request.host, me)})
        else:
            self.redirect('/')

class PersonPage(BaseHandler):
    def get(self):

        hashed_key = self.request.get('id')

        persons = Person.gql("WHERE hashedkey = :1",hashed_key)
        try:
            p = persons[0]
        except IndexError:
            self.show_main_page('Unknown user')
            return

        if p.donator.user_id() == users.get_current_user().user_id():
            me = self.get_or_create_logged_in_person()
            donations = PennyDonation.gql("WHERE donator = :1 ORDER BY date ASC", me)
            donations = list(donations)
            pledged = 0
            for d in donations:
                pledged += len(d.date_list)
            show_payment = pledged >= 1000
            self.render('person',{'donations':donations,'pledged':pledged,'show_payment':show_payment})

class FAQPage(BaseHandler):
    def get(self):
        self.render('faq',{})

class AboutPage(BaseHandler):
    def get(self):
        self.render('about',{})

class Donate(BaseHandler):
    def get(self):

        link = self.request.get('link')

        if not link:
            self.show_main_page('Bad URL')
            return

        from_bookmarklet = self.request.get('bookmarklet') == 'true'

        if from_bookmarklet:
            # Get person from hashedkey in the bookmarklet
            donators = Person.gql("WHERE hashedkey = :1", self.request.get('k'))
            if donators.count() == 1:
                me = donators[0]
            else:
                logging.error('Found '+donators.count()+' People with hashedkey '+self.request.get('k'))
                self.show_main_page('An error occured with your account.')
        else:
            if not users.get_current_user():
                self.redirect(users.create_login_url(self.request.uri))
                return
            else:
                me = self.get_or_create_logged_in_person()

        campaign = Campaign.gql("WHERE link = :1", link)

        if campaign.count() == 0:
            # Create new Campaign
            c = Campaign(link=link, count=1)
            c.put()
            # Create new donation
            d = PennyDonation(donator=me,campaign=c)
            d.date_list.append(datetime.datetime.now())
            d.put()
            if from_bookmarklet:
                self.render('bookmarklet', {'msg':'Donation saved'})
            else:
                self.redirect('profile?id='+me.hashedkey)
        elif campaign.count() == 1:
            c = campaign[0]

            prev_donation = PennyDonation.gql("WHERE campaign = :1 AND donator = :2",c,me)

            if prev_donation.count() == 0:
                # Create new donation
                d = PennyDonation(donator=me,campaign=c)
                d.date_list.append(datetime.datetime.now())
                d.put()
            elif prev_donation.count() == 1:
                # Existing donation - update time to record donation
                d = prev_donation[0]
                d.date_list.append(datetime.datetime.now())
                d.put()
            else:
                logging.error('Found multiple Donations with the same url and user.')
                self.show_main_page('An error occured with your donation.')

            # Keep count of donations for this campaign
            c.count += 1
            c.put()

            if from_bookmarklet:
                self.render('bookmarklet', {'msg':'Donation saved'})
            else:
                self.redirect('profile?id='+me.hashedkey)
        else:
            logging.error('Found multiple Campaigns with the same url.')
            self.show_main_page('An error occured with your donation.')

class UnDonate(BaseHandler):
    def get(self):
        link = self.request.get('link')
        me   = self.get_or_create_logged_in_person()
        c = Campaign.gql("WHERE link = :1", link)[0]
        d = PennyDonation.gql("WHERE campaign = :1 AND donator = :2",c,me)[0]
        sum = len(d.date_list)
        d.delete()
        c.count -= sum
        c.put()
        self.redirect('/profile?id='+me.hashedkey)

application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/home',HomePage),
                                      ('/profile',PersonPage),
                                      ('/about', AboutPage),
                                      ('/faq', FAQPage),
                                      ('/donate', Donate),
                                      ('/undonate', UnDonate),],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
