"""
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
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

############## Models ###################

# Table to store webpages and who should get money if someone donates to this page
class Campaign(db.Model):
    link         = db.LinkProperty(required=True)
    beneficiary  = db.UserProperty()
    created_date = db.DateTimeProperty(auto_now_add=True)
    date         = db.DateTimeProperty(auto_now=True)
    count        = db.IntegerProperty(required=True, default=0)

# Members table - hashedkey is used to avoid login when using bookmarklet
class DiddyMember(db.Model):
    google_user = db.UserProperty(required=True)
    hashedkey   = db.StringProperty()
    def put(self):
        # When stored - create hash of user_id - constant even if user changes email address
        if self.hashedkey is None:
            self.hashedkey = hashlib.sha1(str(self.google_user.user_id())).hexdigest()
        assert self.hashedkey
        return db.Model.put(self)

# Donations table
# Note: multiple donations to the same webpage by the same user are stored in the same entity (via ListProperty)
class PennyDonation(db.Model):
    donator   = db.ReferenceProperty(DiddyMember,required=True)
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

    # Get logged in person and create DiddyMember Entity if doesn't already exist
    def get_or_create_logged_in_person(self):
        if self.logged_in_person:
            return self.logged_in_person
        me = users.get_current_user()
        if me:
            persons = DiddyMember.gql("WHERE google_user = :1",me)
            if persons.count() == 0:
                # Save new DiddyMember to datastore (and auto-generate a hash)
                p = DiddyMember(google_user=users.get_current_user())
                p.put()
            elif persons.count() == 1:
                p = persons[0]
            else:
                logging.error('Found multiple People with the same hashedkey.')
            self.logged_in_person = p
            return self.logged_in_person
        return None

    def render(self, template_name, extra_values={}):

        # Marshal the variables passed to template files
        values = {
        'request': self.request,
        'lip': self.get_or_create_logged_in_person(),
        'login_url': users.create_login_url('/home'),
        'logout_url': users.create_logout_url('http://%s/' % (self.request.host,))}
        values.update(extra_values)

        # Get template file
        template_file = os.path.join(os.path.dirname(__file__), 'templates', template_name + '.html')
        logging.debug(template_file)

        # Render page using given template
        self.response.out.write(template.render(template_file, values, debug=True))

    #Do an internal (non-302) redirect to the front page. Preserves the user agent's requested URL.
    def show_main_page(self, error_msg=None):
        page = MainPage()
        page.request  = self.request
        page.response = self.response
        page.get(error_msg)

############## Handlers #################
class MainPage(BaseHandler):
    def get(self, error_msg=None):
        campaigns = Campaign.gql("ORDER BY date DESC LIMIT 7")
        self.render('index', {'campaigns': campaigns,'error_msg': error_msg})


class GetBookmarkletPage(BaseHandler):
    def get(self):
        if users.get_current_user():
            me = self.get_or_create_logged_in_person()
            self.render('bookmarklet',{'bookmarklet': bookmarklet(self.request.host, me)})
        else:
            logging.info('Non-logged in user trying to access GetBookmarkletPage.')
            self.redirect('/')


class ProfilePage(BaseHandler):
    def get(self):
        me = self.get_or_create_logged_in_person()
        donations = PennyDonation.gql("WHERE donator = :1 ORDER BY date DESC", me)
        donations = list(donations)
        pledged = 0
        for d in donations:
            pledged += len(d.date_list)

        template_values = {
            'donations':donations,
            'pledged':pledged,
            'undonelink':self.request.get('undone'),
            'donatedlink':self.request.get('donated'),
            'deletedlink':self.request.get('delete')}

        self.render('profile',template_values)


class FAQPage(BaseHandler):
    def get(self):
        self.render('faq',{})


class AboutPage(BaseHandler):
    def get(self):
        self.render('about',{})


class CheckOutPage(BaseHandler):
    def get(self):
        self.render('checkout',{})


class Donate(BaseHandler):
    def do_donate(self, link, diddyMember):
        campaign = Campaign.gql("WHERE link = :1", link)

        if campaign.count() == 0:
            # Create new Campaign
            c = Campaign(link=link, count=1)
            c.put()
            # Create new donation
            d = PennyDonation(donator=diddyMember,campaign=c)
            d.date_list.append(datetime.datetime.now())
            d.put()
        elif campaign.count() == 1:
            c = campaign[0]
            prev_donation = PennyDonation.gql("WHERE campaign = :1 AND donator = :2",c,diddyMember)
            if prev_donation.count() == 0:
                # Create new donation
                d = PennyDonation(donator=diddyMember,campaign=c)
                d.date_list.append(datetime.datetime.now())
                d.put()
            elif prev_donation.count() == 1:
                # Existing donation - update time to record donation
                d = prev_donation[0]
                d.date_list.append(datetime.datetime.now())
                d.put()
            else:
                logging.error('Found multiple Donations with the same url and user.')
                return False
            # Keep count of donations for this campaign
            c.count += 1
            c.put()
        else:
            logging.error('Found multiple Campaigns with the same url.')
            self.show_main_page('An error occured with your donation.')
            return False
        return True

    def get(self):

        link = self.request.get('link')

        if not link:
            self.show_main_page('Bad URL')
            return

        from_bookmarklet = self.request.get('bookmarklet') == 'true'

        if from_bookmarklet:
            # Get person from hashedkey in the bookmarklet
            donators = DiddyMember.gql("WHERE hashedkey = :1", self.request.get('k'))
            if donators.count() == 1:
                me = donators[0]
            else:
                logging.error('Found '+str(donators.count())+' People with hashedkey '+self.request.get('k'))
                self.show_main_page('An error occured with your account.')
        else:
            if not users.get_current_user():
                self.redirect(users.create_login_url(self.request.uri))
                return
            else:
                me = self.get_or_create_logged_in_person()

        if self.do_donate(link,me):
            if from_bookmarklet:
                self.render('bookmarklet-popup', {'msg':'Donation saved','nickname':me.google_user.nickname(),'link':link})
            else:
                self.redirect('profile?donated='+link)
        else:
            self.show_main_page('An error occured with your donation.')


class UndoDonation(BaseHandler):
    def get(self):
        link = self.request.get('link')
        me   = self.get_or_create_logged_in_person()
        c = Campaign.gql("WHERE link = :1", link)[0]
        d = PennyDonation.gql("WHERE campaign = :1 AND donator = :2",c,me)[0]
        sum = len(d.date_list)
        if sum == 1:
            d.delete()
        else:
            d.date_list.pop()
            d.put()
        c.count -= 1
        c.put()
        self.redirect('/profile?undone='+link)


class DeleteDonations(BaseHandler):
    def get(self):
        link = self.request.get('link')
        me   = self.get_or_create_logged_in_person()
        c = Campaign.gql("WHERE link = :1", link)[0]
        d = PennyDonation.gql("WHERE campaign = :1 AND donator = :2",c,me)[0]
        sum = len(d.date_list)
        d.delete()
        c.count -= sum
        c.put()
        self.redirect('/profile?delete='+link)


application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/bookmarklet',GetBookmarkletPage),
                                      ('/profile',ProfilePage),
                                      ('/about',AboutPage),
                                      ('/faq',FAQPage),
                                      ('/donate',Donate),
                                      ('/undo',UndoDonation),
                                      ('/delete',DeleteDonations),
                                      ('/checkout',CheckOutPage),],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
