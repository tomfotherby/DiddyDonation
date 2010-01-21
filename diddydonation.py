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
    link        = db.LinkProperty(required=True)
    name        = db.StringProperty()
    beneficiary = db.UserProperty()
    date        = db.DateTimeProperty(auto_now_add=True)
    count       = db.IntegerProperty(required=True, default=0)

class PennyDonation(db.Model):
    campaign = db.ReferenceProperty(Campaign,required=True)
    donator  = db.UserProperty(required=True)
    date     = db.DateTimeProperty(auto_now_add=True)


############# Base Handler ##############
class BaseHandler(webapp.RequestHandler):

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

        template_values = {
          'campaigns': campaigns,
          'error_msg': error_msg,
          }

        self.render('index', template_values)

class HomePage(BaseHandler):
    def get(self):
        if users.get_current_user():
            self.render('person',{})
        else:
            self.redirect('/')

class PersonPage(BaseHandler):
    def get(self):

        user_id = self.request.get('userid')
        lip = users.get_current_user()

        if user_id != lip.user_id():
            self.show_main_page('Todo - show other user profiles')
            return
        else:
            donations = PennyDonation.gql("WHERE donator = :1", lip)

            template_values = {
            'donations': donations,
            }

            self.render('person',template_values)

class FAQPage(BaseHandler):
    def get(self):
        self.render('faq',{})

class AboutPage(BaseHandler):
    def get(self):
        self.render('about',{})

class SeedSiteWithData(BaseHandler):
    def get(self):
        # Create new Campaign
        campaign = Campaign(beneficiary=users.User("tomtest@tomfotherby.com"),
                    name="Bitvolution Wordpress Tutorial",
                    link="http://www.bitvolution.com/web-design-tutorial-centered-area-with-drop-shadow")
        campaign.put()
        self.redirect('/')

class Donate(BaseHandler):
    def get(self):

        if not users.get_current_user():
            self.redirect(users.create_login_url(self.request.uri))
        else:

            donator = users.get_current_user()

            link = self.request.get('link')

            campaign = Campaign.gql("WHERE link = :1", link)
            numFound = campaign.count()

            if numFound == 0:
                # Create new Campaign
                campaign = Campaign(name="todo-get-url-title",link=link, count=1)
                campaign.put()
                # Create new donation
                donation = PennyDonation(donator=donator,campaign=campaign)
                donation.put()
                self.redirect('/')
            elif numFound == 1:
                c = campaign[0]
                # Create new donation
                donation = PennyDonation(donator=donator,campaign=c)
                donation.put()
                # Keep count of donations for this campaign
                c.count += 1
                c.put()
                self.redirect('/')
            else:
                logging.error('Found multiple Campaigns with the same url.')
                self.show_main_page('An error occured with your donation.  Please try again.')


application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/home',HomePage),
                                      ('/profile',PersonPage),
                                      ('/about', AboutPage),
                                      ('/faq', FAQPage),
                                      ('/seed', SeedSiteWithData),
                                      ('/donate', Donate)],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
