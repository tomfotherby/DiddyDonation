import os
import cgi
import hashlib
import Cookie
import logging

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

_DEBUG = False


############## Models ###################

class Campaign(db.Model):
    beneficiary = db.UserProperty(required=True)
    name        = db.StringProperty(required=True)
    link        = db.LinkProperty(required=True)
    count       = db.IntegerProperty(required=True, default=0)
    date        = db.DateTimeProperty(auto_now_add=True)

class PennyDonation(db.Model):
    donator  = db.UserProperty(required=True)
    campaign = db.ReferenceProperty(Campaign)
    date     = db.DateTimeProperty(auto_now_add=True)


############# Base Handler ##############
class BaseHandler(webapp.RequestHandler):

    def render(self, template_name, extra_values={}):

        values = {
        'request': self.request,
        'user': users.get_current_user(),
        'login_url': users.create_login_url('/home'),
        'logout_url': users.create_logout_url('http://%s/' % (self.request.host,)),
        'debug': self.request.get('deb')}

        values.update(extra_values)
        cwd = os.path.dirname(__file__)
        path = os.path.join(cwd, 'templates', template_name + '.html')
        logging.debug(path)
        self.response.out.write(template.render(path, values, debug=_DEBUG))


############## Handlers #################
class MainPage(BaseHandler):
    def get(self, error_msg=None):

        campaigns = Campaign.gql("ORDER BY date DESC LIMIT 7")

        template_values = {
          'campaigns': campaigns,
          'error_msg': error_msg,
          }

        self.render('index', template_values)

class HomePage(BaseHandler):
    def get(self):
        if users.get_current_user():
            self.render('home',{})
        else:
            self.redirect('/')

class FAQPage(BaseHandler):
    def get(self):
        self.render('faq',{})

class AboutPage(BaseHandler):
    def get(self):
        self.render('about',{})

class SeedSiteWithData(webapp.RequestHandler):
    def get(self):
        # Create new Campaign
        campaign = Campaign(beneficiary=users.User("tomtest@tomfotherby.com"),
                    name="Bitvolution Wordpress Tutorial",
                    link="http://www.bitvolution.com/web-design-tutorial-centered-area-with-drop-shadow")
        campaign.put()
        self.redirect('/')

class Donate(webapp.RequestHandler):
    def get(self):

        if not users.get_current_user():
            self.redirect(users.create_login_url(self.request.uri))
        else:
            donator  = users.get_current_user()
            campaign_key = db.Key(self.request.get('key'))

            # Create new donation
            donation = PennyDonation(donator=donator,campaign=campaign_key)
            donation.put()

            # Keep count of donations for this campaign
            campaign = db.get(campaign_key);
            campaign.count += 1;
            campaign.put()
            self.redirect('/')

application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/home',HomePage),
                                      ('/about', AboutPage),
                                      ('/faq', FAQPage),
                                      ('/seed', SeedSiteWithData),
                                      ('/donate', Donate)],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
