/* StickLLM offline stand-in for the removed analytics helpers.
   The editor calls gaEvent and gaTiming. These no-ops keep those calls
   from throwing and from sending anything off the stick. */
function gaEvent() {}
function gaTiming() {}
